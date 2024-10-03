document.getElementById('optionsForm').addEventListener('submit', function(e) {
    e.preventDefault();
    const symbol = document.getElementById('symbol').value;
    const resultsDiv = document.getElementById('results');
    resultsDiv.innerHTML = '<p>Loading...</p>';

    fetch('/get_options', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify({ symbol: symbol })
    })
    .then(response => {
        if (!response.ok) {
            return response.json().then(err => {
                throw new Error(err.error || `HTTP error! status: ${response.status}`);
            });
        }
        return response.json();
    })
    .then(data => {
        let output = `<h2>Current Price: $${data.current_price.toFixed(2)}</h2>`;
        for (const [expiration, expirationData] of Object.entries(data.expirations)) {
            output += `<h2>Expiration: ${expiration}</h2>`;
            output += `<div class="summary">
                <p><strong>Put/Call Ratio:</strong> ${expirationData.put_call_ratio.toFixed(2)}</p>
                <p><strong>Outlook:</strong> <span class="${expirationData.outlook}">${expirationData.outlook}</span></p>
                <p><strong>Max Pain:</strong> $${expirationData.max_pain.toFixed(2)}</p>
                <p><strong>Expected Move:</strong> $${expirationData.expected_move.toFixed(2)}</p>
            </div>`;
            if (expirationData.options.length === 0) {
                output += '<p>No options available for this expiration date.</p>';
            } else {
                output += '<table><tr><th>Strike</th><th>Bid</th><th>Ask</th><th>Delta</th><th>IV</th><th>Volume</th><th>OI</th><th>Ann. Return</th></tr>';
                expirationData.options.forEach(option => {
                    output += `<tr>
                        <td>$${option.Strike.toFixed(2)}</td>
                        <td>$${option.Bid.toFixed(2)}</td>
                        <td>$${option.Ask.toFixed(2)}</td>
                        <td>${option.Delta.toFixed(3)}</td>
                        <td>${(option.IV * 100).toFixed(2)}%</td>
                        <td>${option.Volume}</td>
                        <td>${option['Open Interest']}</td>
                        <td>${option['Annualized Return']}</td>
                    </tr>`;
                });
                output += '</table>';
            }
        }
        resultsDiv.innerHTML = output;
    })
    .catch(error => {
        console.error('Error:', error);
        resultsDiv.innerHTML = `<p class="error">An error occurred: ${error.message}</p>`;
    });
});