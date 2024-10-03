import requests
import os
import logging
import numpy as np
from dotenv import load_dotenv
from datetime import datetime, date
from flask import Flask, request, jsonify, render_template
from flask_cors import CORS

# Set up logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

# Tradier API configuration
TRADIER_API_KEY = os.getenv('TRADIER_API_KEY')
TRADIER_API_BASE_URL = 'https://api.tradier.com/v1'  # Production URL

app = Flask(__name__)
CORS(app)

def check_api_key():
    if not TRADIER_API_KEY:
        raise ValueError("TRADIER_API_KEY is not set in the environment variables.")

def make_api_request(endpoint, params=None):
    headers = {
        'Authorization': f'Bearer {TRADIER_API_KEY}',
        'Accept': 'application/json'
    }
    
    try:
        response = requests.get(f'{TRADIER_API_BASE_URL}/{endpoint}', headers=headers, params=params)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.HTTPError as e:
        logger.error(f"HTTP error occurred: {e}")
        logger.error(f"Response content: {e.response.content}")
        if e.response.status_code == 401:
            raise ValueError("API key is invalid or has expired")
        raise
    except requests.exceptions.RequestException as e:
        logger.error(f"Request error occurred: {e}")
        raise

def get_option_expirations(symbol):
    params = {
        'symbol': symbol,
        'includeAllRoots': 'true',
        'strikes': 'false'
    }
    data = make_api_request('markets/options/expirations', params)
    return data.get('expirations', {}).get('date', [])

def get_option_chain(symbol, expiration):
    params = {
        'symbol': symbol,
        'expiration': expiration,
        'greeks': 'true'
    }
    data = make_api_request('markets/options/chains', params)
    return data.get('options', {}).get('option', [])

def get_stock_price(symbol):
    params = {
        'symbols': symbol,
        'greeks': 'false'
    }
    data = make_api_request('markets/quotes', params)
    return data.get('quotes', {}).get('quote', {}).get('last')

def get_next_two_expirations(expirations):
    today = date.today()
    future_expirations = [exp for exp in expirations if datetime.strptime(exp, '%Y-%m-%d').date() > today]
    return future_expirations[:2]

def filter_and_format_options(options, max_delta=0.15, min_volume=250, min_open_interest=500, max_strike=30):
    filtered_options = []
    for option in options:
        if (option['option_type'] == 'put' and
            abs(float(option['greeks']['delta'])) <= max_delta and
            int(option['volume']) >= min_volume and
            int(option['open_interest']) >= min_open_interest and
            float(option['strike']) <= max_strike):
            
            formatted_option = {
                "Symbol": option['symbol'],
                "Strike": float(option['strike']),
                "Bid": float(option['bid']),
                "Ask": float(option['ask']),
                "Volume": int(option['volume']),
                "Open Interest": int(option['open_interest']),
                "Delta": float(option['greeks']['delta']),
                "IV": float(option['greeks'].get('mid_iv', option['greeks'].get('ask_iv', 0))),
                "Theta": float(option['greeks']['theta']),
                "Expiration": option['expiration_date']
            }
            filtered_options.append(formatted_option)
    
    return filtered_options

def calculate_annualized_return(premium, strike_price, days_to_expiration):
    return (premium / strike_price) * (365 / days_to_expiration)

def calculate_put_call_ratio(options):
    put_volume = sum(int(option['volume']) for option in options if option['option_type'] == 'put')
    call_volume = sum(int(option['volume']) for option in options if option['option_type'] == 'call')
    
    if call_volume == 0:
        return float('inf')  # Avoid division by zero
    
    return put_volume / call_volume

def interpret_put_call_ratio(ratio):
    if ratio > 1:
        return "Bearish"
    elif ratio < 1:
        return "Bullish"
    else:
        return "Neutral"

def calculate_max_pain(options):
    strikes = sorted(set(float(option['strike']) for option in options))
    
    pain = {}
    for strike in strikes:
        total_pain = sum(
            max(0, strike - float(option['strike'])) * int(option['open_interest'])
            if option['option_type'] == 'call'
            else max(0, float(option['strike']) - strike) * int(option['open_interest'])
            for option in options
        )
        pain[strike] = total_pain
    
    return min(pain, key=pain.get)

def calculate_expected_move(options, current_price, days_to_expiration):
    atm_strike = min(options, key=lambda x: abs(float(x['strike']) - current_price))
    atm_call = next((opt for opt in options if opt['option_type'] == 'call' and opt['strike'] == atm_strike['strike']), None)
    atm_put = next((opt for opt in options if opt['option_type'] == 'put' and opt['strike'] == atm_strike['strike']), None)
    
    if atm_call and atm_put:
        atm_straddle = float(atm_call['ask']) + float(atm_put['ask'])
        return atm_straddle * np.sqrt(days_to_expiration / 365)
    else:
        return None

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/get_options', methods=['POST'])
def get_options():
    data = request.json
    symbol = data.get('symbol')
    
    if not symbol:
        return jsonify({"error": "No symbol provided"}), 400

    try:
        check_api_key()
        
        current_price = get_stock_price(symbol)
        if not current_price:
            return jsonify({"error": "Failed to fetch current stock price"}), 500

        all_expirations = get_option_expirations(symbol)
        if not all_expirations:
            return jsonify({"error": "No expirations available for this symbol"}), 404

        next_two_expirations = get_next_two_expirations(all_expirations)
        if len(next_two_expirations) < 2:
            return jsonify({"error": "Not enough future expirations available"}), 400

        results = {}
        
        for expiration in next_two_expirations:
            option_chain = get_option_chain(symbol, expiration)
            if option_chain:
                put_call_ratio = calculate_put_call_ratio(option_chain)
                outlook = interpret_put_call_ratio(put_call_ratio)
                max_pain = calculate_max_pain(option_chain)
                
                days_to_expiration = (datetime.strptime(expiration, '%Y-%m-%d').date() - date.today()).days
                expected_move = calculate_expected_move(option_chain, current_price, days_to_expiration)
                
                filtered_options = filter_and_format_options(option_chain)
                formatted_options = []
                for option in filtered_options:
                    days_to_expiration = (datetime.strptime(option['Expiration'], '%Y-%m-%d').date() - date.today()).days
                    annualized_return = calculate_annualized_return(option['Bid'], option['Strike'], days_to_expiration)
                    option['Annualized Return'] = f"{annualized_return:.2%}"
                    formatted_options.append(option)
                
                results[expiration] = {
                    "options": formatted_options,
                    "put_call_ratio": put_call_ratio,
                    "outlook": outlook,
                    "max_pain": max_pain,
                    "expected_move": expected_move
                }
            else:
                results[expiration] = {
                    "options": [],
                    "put_call_ratio": None,
                    "outlook": "Unable to determine",
                    "max_pain": None,
                    "expected_move": None
                }

        return jsonify({"current_price": current_price, "expirations": results})
    except ValueError as e:
        logger.error(f"ValueError: {str(e)}")
        return jsonify({"error": str(e)}), 401
    except Exception as e:
        logger.error(f"Unexpected error: {str(e)}")
        return jsonify({"error": "An unexpected error occurred"}), 500

if __name__ == "__main__":
    try:
        check_api_key()
        app.run(debug=True, port=5000)
    except ValueError as e:
        logger.error(str(e))
        exit(1)