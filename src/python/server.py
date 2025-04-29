import os
import sys

# Import other packages first
import json
import base64
import threading
import time
import uuid
from io import BytesIO
from PIL import Image
import numpy as np
import cv2
from flask import Flask, request, jsonify, send_file, make_response
from flask_cors import CORS

# Check for bundled packages directory relative to the executable
bundled_packages_dir = os.path.abspath(os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 
    'python_packages'
))

# Try importing from system packages first
try:
    import asyncio
    from coffeeblack import Argus
    print("Using system Python packages")
except ImportError:
    # If system packages fail, try bundled packages
    if os.path.exists(bundled_packages_dir):
        print(f"Using bundled Python packages from: {bundled_packages_dir}")
        sys.path.insert(0, bundled_packages_dir)
        try:
            import asyncio
            from coffeeblack import Argus
        except (ImportError, SyntaxError) as e:
            print(f"Error importing bundled packages: {e}")
            sys.path.pop(0)
            raise
    else:
        print("Neither system nor bundled packages found")
        raise

print("Python version:", sys.version)
print("Working directory:", os.getcwd())

try:
    HAS_COFFEEBLACK = True
    print("CoffeeBlack import successful")
except ImportError as e:
    print(f"Warning: coffeeblack package not found: {str(e)}. Install it for full functionality.")
    HAS_COFFEEBLACK = False

# Constants
IMAGES_DIR = os.path.join(os.path.dirname(__file__), 'images')
REFERENCE_ELEMENTS_DIR = os.path.join(os.path.dirname(__file__), 'reference_elements')
os.makedirs(IMAGES_DIR, exist_ok=True)
os.makedirs(REFERENCE_ELEMENTS_DIR, exist_ok=True)

# Runtime API key storage (in case it's updated while running)
RUNTIME_API_KEY = os.environ.get("COFFEEBLACK_API_KEY", "")

# Initialize Flask app
app = Flask(__name__)

# Configure CORS - allow everything
CORS(app, resources={
    r"/*": {
        "origins": "*",
        "methods": ["GET", "POST", "OPTIONS"],
        "allow_headers": ["Content-Type", "Authorization", "X-Requested-With"],
        "supports_credentials": True
    }
})

# Debug every request received and response sent
@app.before_request
def log_request():
    print(f"\n--- Request received ---")
    print(f"Method: {request.method}")
    print(f"Path: {request.path}")
    print(f"Headers: {dict(request.headers)}")
    print(f"Remote addr: {request.remote_addr}")
    if request.is_json:
        print(f"JSON data: {request.json}")
    elif request.form:
        print(f"Form data: {request.form}")
    elif request.files:
        print(f"Files: {list(request.files.keys())}")
    
    # Handle preflight requests
    if request.method == "OPTIONS":
        response = make_response()
        response.headers.add("Access-Control-Allow-Origin", "*")
        response.headers.add("Access-Control-Allow-Headers", "Content-Type, Authorization, X-Requested-With")
        response.headers.add("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        response.headers.add("Access-Control-Allow-Credentials", "true")
        return response

@app.after_request
def log_response(response):
    print(f"\n--- Response sent ---")
    print(f"Status: {response.status}")
    print(f"Headers: {dict(response.headers)}")
    print(f"Data: {response.get_data(as_text=True)[:200]}...")  # First 200 chars
    
    # Ensure CORS headers on every response
    response.headers.add("Access-Control-Allow-Origin", "*")
    response.headers.add("Access-Control-Allow-Headers", "Content-Type, Authorization, X-Requested-With")
    response.headers.add("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
    response.headers.add("Access-Control-Allow-Credentials", "true")
    return response

# Global state
reference_images = {}
automation_running = False
automation_thread = None
stop_automation = False
sdk_instance = None
tinder_automation = {
    'running': False,
    'paused': False,
    'config': {
        'similarity_mode': 'similar',
        'similarity_thresholds': {
            'similar': 0.05,    # Higher value means more different (1 - 0.4 = 0.6)
            'very_similar': 0.15,  # More strict (1 - 0.6 = 0.4)
            'clone': 0.2      # Most strict (1 - 0.8 = 0.2)
        },
        'max_swipes': 100
    },
    'stats': {
        'total_profiles': 0,
        'likes': 0,
        'dislikes': 0,
        'matches': 0,
        'start_time': None,
        'end_time': None,
        'similarity_metrics': {
            'likes_avg_similarity': 0.0,
            'dislikes_avg_similarity': 0.0,
            'total_avg_similarity': 0.0,
            'max_similarity': 0.0,
            'min_similarity': 1.0,
            'similarity_history': []
        }
    },
    'recent_decisions': []
}

def get_sdk():
    """Get or create a CoffeeBlackSDK instance"""
    global sdk_instance
    
    if not HAS_COFFEEBLACK:
        return None
        
    if sdk_instance is None:
        # Use runtime API key which can be updated via the set-api-key endpoint
        api_key = RUNTIME_API_KEY or os.environ.get("COFFEEBLACK_API_KEY", "")
        
        # Check if Argus is available (newer SDK version)
        try:
            from coffeeblack import Argus
            print("Using Argus SDK (newer version)")
            sdk_instance = Argus(
                api_key=api_key,
                verbose=True,
                debug_enabled=True,
                elements_conf=0.4,
                rows_conf=0.3,
                container_conf=0.3,
                model="ui-detect"
            )
        except ImportError:
            # Fall back to CoffeeBlackSDK (older version)
            print("Using CoffeeBlackSDK (older version)")
            sdk_instance = CoffeeBlackSDK(
                api_key=api_key,
                verbose=True,
                debug_enabled=True,
                elements_conf=0.4,
                rows_conf=0.3,
                container_conf=0.3,
                model="ui-detect"
            )
    
    return sdk_instance


# Image comparison function
def compare_images(img1, img2):
    """
    Compare two images and return a similarity score between 0 and 1
    """
    try:
        # Convert images to the same size - with consistent dimensions for comparison
        target_size = (400, 400)  # Larger size for better detail comparison
        img1 = cv2.resize(img1, target_size)
        img2 = cv2.resize(img2, target_size)
        
        # Convert to grayscale
        gray1 = cv2.cvtColor(img1, cv2.COLOR_BGR2GRAY)
        gray2 = cv2.cvtColor(img2, cv2.COLOR_BGR2GRAY)
        
        # Initialize SIFT detector with increased features
        sift = cv2.SIFT_create(nfeatures=200)  # Increased from default for better matching
        
        # Find keypoints and descriptors
        kp1, des1 = sift.detectAndCompute(gray1, None)
        kp2, des2 = sift.detectAndCompute(gray2, None)
        
        # If no keypoints found, return 0 similarity
        if des1 is None or des2 is None or len(des1) < 2 or len(des2) < 2:
            return 0.0
        
        # Create BF Matcher with improved ratio test
        bf = cv2.BFMatcher()
        matches = bf.knnMatch(des1, des2, k=2)
        
        # Apply ratio test - use a slightly more lenient ratio for better matching
        good_matches = []
        for m, n in matches:
            if m.distance < 0.8 * n.distance:  # 0.8 instead of 0.75 for more matches
                good_matches.append(m)
        
        # Calculate similarity score with a better scaling factor
        similarity = len(good_matches) / max(min(len(kp1), len(kp2)), 1)
        return min(similarity * 2.5, 1.0)  # Increased scaling factor for better results
        
    except Exception as e:
        print(f"Error comparing images: {str(e)}")
        return 0.0


# Helper function to run an async function in a synchronous context
def run_async(coro):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# Basic CoffeeBlack SDK action routes
@app.route('/cb/status', methods=['OPTIONS'])
def cb_status_options():
    """Handle OPTIONS requests for /cb/status"""
    print("OPTIONS request received for /cb/status")
    response = make_response()
    response.headers.add("Access-Control-Allow-Origin", "*")
    response.headers.add("Access-Control-Allow-Methods", "GET, OPTIONS")
    response.headers.add("Access-Control-Allow-Headers", "Content-Type, Authorization, X-Requested-With")
    response.headers.add("Access-Control-Max-Age", "3600")
    return response

@app.route('/cb/status', methods=['GET'])
def cb_status():
    """Get status of the CoffeeBlack SDK"""
    try:
        print(f"\n>>> cb_status route called - request method: {request.method}")
        print(f">>> Raw request headers: {request.headers}")
        print(f">>> Query params: {request.args}")
        print(f">>> Request json: {request.get_json(silent=True)}")
        print(f">>> Request remote addr: {request.remote_addr}")
        print(f">>> Request user agent: {request.user_agent}")
        print(f">>> Has coffeeblack: {HAS_COFFEEBLACK}")
        
        response = jsonify({
            'status': 'available' if HAS_COFFEEBLACK else 'unavailable',
            'api_key_set': bool(RUNTIME_API_KEY or os.environ.get("COFFEEBLACK_API_KEY")),
            'message': 'CoffeeBlack SDK is ready' if HAS_COFFEEBLACK else 'CoffeeBlack SDK is not installed'
        })
        
        # Manually ensure CORS headers are set
        response.headers.add("Access-Control-Allow-Origin", "*")
        response.headers.add("Access-Control-Allow-Headers", "Content-Type, Authorization, X-Requested-With")
        response.headers.add("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        
        print(f">>> Sending response: {response.get_data(as_text=True)}")
        return response
        
    except Exception as e:
        print(f">>> ERROR in cb_status route: {str(e)}")
        error_response = jsonify({
            'status': 'error',
            'error': str(e),
            'message': 'An error occurred processing the status request'
        })
        error_response.headers.add("Access-Control-Allow-Origin", "*")
        return error_response, 500

@app.route('/cb/set-api-key', methods=['POST'])
def set_api_key():
    """Set the CoffeeBlack API key at runtime"""
    global RUNTIME_API_KEY, sdk_instance
    
    try:
        data = request.json
        if not data or 'api_key' not in data:
            return jsonify({'success': False, 'error': 'No API key provided'})
        
        api_key = data['api_key']
        
        # Store the API key
        RUNTIME_API_KEY = api_key
        
        # Reset SDK instance to recreate with new API key
        sdk_instance = None
        
        return jsonify({
            'success': True,
            'message': 'API key set successfully',
            'api_key_set': bool(RUNTIME_API_KEY)
        })
        
    except Exception as e:
        print(f"Error setting API key: {str(e)}")
        return jsonify({'success': False, 'error': str(e)})

@app.route('/cb/open-app', methods=['POST'])
def open_app():
    """Open an application using CoffeeBlack SDK"""
    if not HAS_COFFEEBLACK:
        return jsonify({'success': False, 'error': 'CoffeeBlack SDK is not installed'})
    
    try:
        data = request.json
        if not data or 'app_name' not in data:
            return jsonify({'success': False, 'error': 'No app name provided'})
        
        app_name = data['app_name']
        wait_time = data.get('wait_time', 2.0)
        
        sdk = get_sdk()
        result = run_async(sdk.open_and_attach_to_app(app_name, wait_time=wait_time))
        
        return jsonify({
            'success': True,
            'message': f'Successfully opened app: {app_name}',
            'result': str(result)
        })
        
    except Exception as e:
        print(f"Error opening app: {str(e)}")
        return jsonify({'success': False, 'error': str(e)})


@app.route('/cb/execute-action', methods=['POST'])
def execute_action():
    """Execute an action using CoffeeBlack SDK"""
    if not HAS_COFFEEBLACK:
        return jsonify({'success': False, 'error': 'CoffeeBlack SDK is not installed'})
    
    try:
        data = request.json
        if not data or 'query' not in data:
            return jsonify({'success': False, 'error': 'No query provided'})
        
        query = data['query']
        reference_element = data.get('reference_element')
        elements_conf = data.get('elements_conf', 0.4)
        container_conf = data.get('container_conf', 0.3)
        
        # Handle reference element if provided
        ref_element_path = None
        if reference_element and reference_element.endswith('.png'):
            # Check if the reference element exists in the reference_elements directory
            ref_element_path = os.path.join(REFERENCE_ELEMENTS_DIR, reference_element)
            if not os.path.exists(ref_element_path):
                return jsonify({
                    'success': False, 
                    'error': f'Reference element not found: {reference_element}'
                })
        
        sdk = get_sdk()
        result = run_async(sdk.execute_action(
            query=query,
            reference_element=ref_element_path,
            elements_conf=elements_conf,
            container_conf=container_conf
        ))
        
        return jsonify({
            'success': True,
            'message': f'Successfully executed action: {query}',
            'chosen_element_index': result.chosen_element_index,
            'explanation': result.explanation
        })
        
    except Exception as e:
        print(f"Error executing action: {str(e)}")
        return jsonify({'success': False, 'error': str(e)})


@app.route('/cb/press-key', methods=['POST'])
def press_key():
    """Press a key using CoffeeBlack SDK"""
    if not HAS_COFFEEBLACK:
        return jsonify({'success': False, 'error': 'CoffeeBlack SDK is not installed'})
    
    try:
        data = request.json
        if not data or 'key' not in data:
            return jsonify({'success': False, 'error': 'No key provided'})
        
        key = data['key']
        
        sdk = get_sdk()
        result = run_async(sdk.press_key(key))
        
        return jsonify({
            'success': True,
            'message': f'Successfully pressed key: {key}',
            'result': str(result)
        })
        
    except Exception as e:
        print(f"Error pressing key: {str(e)}")
        return jsonify({'success': False, 'error': str(e)})


@app.route('/cb/see', methods=['POST'])
def see():
    """Use the see method to check if an element is visible"""
    if not HAS_COFFEEBLACK:
        return jsonify({'success': False, 'error': 'CoffeeBlack SDK is not installed'})
    
    try:
        data = request.json
        if not data or 'description' not in data:
            return jsonify({'success': False, 'error': 'No description provided'})
        
        description = data['description']
        wait = data.get('wait', True)
        timeout = data.get('timeout', 5.0)
        interval = data.get('interval', 0.5)
        
        sdk = get_sdk()
        result = run_async(sdk.see(
            description=description,
            wait=wait,
            timeout=timeout,
            interval=interval
        ))
        
        return jsonify({
            'success': True,
            'matches': result.get('matches', False),
            'elements': result.get('elements', []),
            'message': f'Element {"found" if result.get("matches", False) else "not found"}: {description}'
        })
        
    except Exception as e:
        print(f"Error using see method: {str(e)}")
        return jsonify({'success': False, 'error': str(e)})


@app.route('/cb/screenshot', methods=['GET'])
def get_screenshot():
    """Get a screenshot using CoffeeBlack SDK"""
    if not HAS_COFFEEBLACK:
        return jsonify({'success': False, 'error': 'CoffeeBlack SDK is not installed'})
    
    try:
        sdk = get_sdk()
        screenshot_data = run_async(sdk.get_screenshot())
        
        # Convert bytes to base64
        screenshot_base64 = base64.b64encode(screenshot_data).decode('utf-8')
        
        return jsonify({
            'success': True,
            'screenshot': screenshot_base64
        })
        
    except Exception as e:
        print(f"Error getting screenshot: {str(e)}")
        return jsonify({'success': False, 'error': str(e)})


@app.route('/cb/upload-reference-element', methods=['POST'])
def upload_reference_element():
    """Upload a reference element image for later use with execute_action"""
    try:
        if 'file' not in request.files:
            return jsonify({'success': False, 'error': 'No file provided'})
        
        file = request.files['file']
        if not file.filename:
            return jsonify({'success': False, 'error': 'No filename provided'})
        
        # Save the file to the reference_elements directory
        filename = file.filename
        filepath = os.path.join(REFERENCE_ELEMENTS_DIR, filename)
        file.save(filepath)
        
        return jsonify({
            'success': True,
            'message': f'Reference element uploaded successfully: {filename}',
            'path': filepath
        })
        
    except Exception as e:
        print(f"Error uploading reference element: {str(e)}")
        return jsonify({'success': False, 'error': str(e)})


@app.route('/cb/list-reference-elements', methods=['GET'])
def list_reference_elements():
    """List all available reference elements"""
    try:
        elements = []
        
        if os.path.exists(REFERENCE_ELEMENTS_DIR):
            for filename in os.listdir(REFERENCE_ELEMENTS_DIR):
                if filename.endswith('.png'):
                    file_path = os.path.join(REFERENCE_ELEMENTS_DIR, filename)
                    elements.append({
                        'name': filename,
                        'path': file_path,
                        'size': os.path.getsize(file_path),
                        'modified': os.path.getmtime(file_path)
                    })
        
        return jsonify({
            'success': True,
            'elements': elements
        })
        
    except Exception as e:
        print(f"Error listing reference elements: {str(e)}")
        return jsonify({'success': False, 'error': str(e)})


@app.route('/cb/reference-element/<filename>', methods=['GET'])
def get_reference_element(filename):
    """Get a reference element image by filename"""
    try:
        file_path = os.path.join(REFERENCE_ELEMENTS_DIR, filename)
        
        if not os.path.exists(file_path):
            return jsonify({'success': False, 'error': f'Reference element not found: {filename}'}), 404
        
        return send_file(file_path, mimetype='image/png')
        
    except Exception as e:
        print(f"Error getting reference element: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/cb/navigate-url', methods=['POST'])
def navigate_url():
    """Navigate to a URL using CoffeeBlack SDK"""
    if not HAS_COFFEEBLACK:
        return jsonify({'success': False, 'error': 'CoffeeBlack SDK is not installed'})
    
    try:
        data = request.json
        if not data or 'url' not in data:
            return jsonify({'success': False, 'error': 'No URL provided'})
        
        url = data['url']
        browser_name = data.get('browser', 'Safari')
        
        sdk = get_sdk()
        
        # First open the browser
        result_open = run_async(sdk.open_and_attach_to_app(browser_name, wait_time=2.0))
        
        # Type the URL
        result_type = run_async(sdk.execute_action(f"Use the keyboard command. Type '{url}' into the url bar"))
        
        # Press enter
        result_enter = run_async(sdk.press_key("enter"))
        
        return jsonify({
            'success': True,
            'message': f'Successfully navigated to: {url}',
            'open_result': str(result_open),
            'type_result': str(result_type),
            'enter_result': str(result_enter)
        })
        
    except Exception as e:
        print(f"Error navigating to URL: {str(e)}")
        return jsonify({'success': False, 'error': str(e)})


# REST API routes
@app.route('/ping', methods=['GET'])
def ping():
    """Simple ping to check if server is running"""
    try:
        print("Ping received")
        return jsonify({
            'status': 'ok',
            'message': 'Server is running'
        })
    except Exception as e:
        print(f"Error in ping: {str(e)}")
        return jsonify({
            'status': 'error',
            'error': str(e)
        }), 500

@app.route('/status', methods=['GET'])
def status():
    return jsonify({
        'status': 'running',
        'automation_running': automation_running,
        'reference_images_count': len(reference_images),
        'coffeeblack_available': HAS_COFFEEBLACK
    })


@app.route('/upload-image', methods=['POST'])
def upload_image():
    try:
        data = request.json
        
        if not data or 'image' not in data:
            return jsonify({'success': False, 'error': 'No image data provided'})
        
        # Extract base64 image data
        image_data = data['image']
        
        # Remove the header if present
        if ',' in image_data:
            image_data = image_data.split(',')[1]
        
        # Decode base64 data
        image_bytes = base64.b64decode(image_data)
        
        # Convert to image
        image = Image.open(BytesIO(image_bytes))
        
        # Convert to OpenCV format for processing
        opencv_image = cv2.cvtColor(np.array(image), cv2.COLOR_RGB2BGR)
        
        # Generate a unique ID for this image
        image_id = str(uuid.uuid4())
        
        # Save to our in-memory store
        reference_images[image_id] = {
            'image': opencv_image,
            'timestamp': time.time()
        }
        
        # Save to disk for persistence
        image_path = os.path.join(IMAGES_DIR, f"{image_id}.jpg")
        cv2.imwrite(image_path, opencv_image)
        
        print(f"Image uploaded and saved with ID: {image_id}")
        
        return jsonify({
            'success': True,
            'id': image_id,
            'message': 'Image uploaded successfully'
        })
        
    except Exception as e:
        print(f"Error processing image upload: {str(e)}")
        return jsonify({'success': False, 'error': str(e)})


@app.route('/start-tinder', methods=['POST'])
def start_tinder():
    """
    Start Tinder automation
    """
    global reference_images, automation_running, automation_thread, stop_automation
    
    try:
        data = request.json
        print("Start Tinder data:", json.dumps(data, indent=2))
        
        # Extract parameters from request
        similarity_mode = data.get('similarityMode', 'similar')
        max_swipes = data.get('maxSwipes', 100)
        reference_images_data = data.get('referenceImages', [])
        
        # Process reference images
        reference_images = {}
        for idx, img_data in enumerate(reference_images_data):
            img_id = f"ref_{idx}"
            
            if isinstance(img_data, dict):
                # New format with type and data/path
                if img_data.get('type') == 'file':
                    # File path provided
                    file_path = img_data.get('path')
                    if os.path.exists(file_path):
                        try:
                            # Load image from file path
                            img = cv2.imread(file_path)
                            if img is not None:
                                # Store directly as numpy array
                                reference_images[img_id] = img
                                print(f"Loaded reference image from file: {file_path}")
                            else:
                                # Fallback to data URL if available
                                base64_img = img_data.get('data', '').split(',')[1] if ',' in img_data.get('data', '') else img_data.get('data', '')
                                img_bytes = base64.b64decode(base64_img)
                                nparr = np.frombuffer(img_bytes, np.uint8)
                                img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
                                # Store directly as numpy array
                                reference_images[img_id] = img
                                print(f"Failed to load from file, used data URL for: {img_id}")
                        except Exception as e:
                            print(f"Error loading image from file {file_path}: {e}")
                            # Fallback to data URL if available
                            if 'data' in img_data:
                                try:
                                    base64_img = img_data['data'].split(',')[1] if ',' in img_data['data'] else img_data['data']
                                    img_bytes = base64.b64decode(base64_img)
                                    nparr = np.frombuffer(img_bytes, np.uint8)
                                    img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
                                    # Store directly as numpy array
                                    reference_images[img_id] = img
                                    print(f"Used data URL fallback for: {img_id}")
                                except Exception as e2:
                                    print(f"Error decoding data URL: {e2}")
                elif img_data.get('type') == 'data':
                    # Data URL provided
                    try:
                        base64_img = img_data['data'].split(',')[1] if ',' in img_data['data'] else img_data['data']
                        img_bytes = base64.b64decode(base64_img)
                        nparr = np.frombuffer(img_bytes, np.uint8)
                        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
                        # Store directly as numpy array
                        reference_images[img_id] = img
                        print(f"Loaded reference image from data URL: {img_id}")
                    except Exception as e:
                        print(f"Error decoding data URL: {e}")
            else:
                # Old format - directly base64 string
                try:
                    base64_img = img_data.split(',')[1] if ',' in img_data else img_data
                    img_bytes = base64.b64decode(base64_img)
                    nparr = np.frombuffer(img_bytes, np.uint8)
                    img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
                    # Store directly as numpy array
                    reference_images[img_id] = img
                    print(f"Loaded reference image (old format): {img_id}")
                except Exception as e:
                    print(f"Error decoding image data: {e}")
        
        # Check if we have any reference images
        if not reference_images:
            return jsonify({'success': False, 'error': 'No valid reference images provided'})
        
        print(f"Loaded {len(reference_images)} reference images")
        
        # Save parameters for automation
        tinder_config = {
            'similarity_mode': similarity_mode,
            'max_swipes': max_swipes
        }
        
        # Start automation in a separate thread
        if not automation_running:
            automation_running = True
            stop_automation = False
            automation_thread = threading.Thread(target=tinder_automation_loop, 
                                               args=(reference_images, tinder_config))
            automation_thread.daemon = True
            automation_thread.start()
            
            return jsonify({
                'success': True, 
                'message': 'Tinder automation started',
                'config': tinder_config,
                'reference_images_count': len(reference_images)
            })
        else:
            return jsonify({
                'success': False, 
                'error': 'Automation already running'
            })
        
    except Exception as e:
        print(f"Error starting Tinder automation: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        })


@app.route('/stop-tinder', methods=['POST'])
def stop_tinder():
    global automation_running, stop_automation, tinder_automation
    
    if not automation_running and not tinder_automation['running']:
        return jsonify({
            'success': False,
            'error': 'No automation is currently running'
        })
    
    try:
        # Stop both automation systems
        stop_automation = True
        tinder_automation['running'] = False
        tinder_automation['paused'] = False
        tinder_automation['stats']['end_time'] = time.time()
        
        return jsonify({
            'success': True,
            'message': 'Stopping Tinder automation...',
            'stats': tinder_automation['stats']
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        })


# Load saved reference images on startup
def load_saved_images():
    try:
        if not os.path.exists(IMAGES_DIR):
            return
            
        for filename in os.listdir(IMAGES_DIR):
            if not filename.endswith('.jpg'):
                continue
                
            image_id = filename.split('.')[0]
            image_path = os.path.join(IMAGES_DIR, filename)
            
            # Load the image
            opencv_image = cv2.imread(image_path)
            
            if opencv_image is not None:
                reference_images[image_id] = {
                    'image': opencv_image,
                    'timestamp': os.path.getmtime(image_path)
                }
                print(f"Loaded saved image: {image_id}")
            
    except Exception as e:
        print(f"Error loading saved images: {str(e)}")


# Tinder Automation Routes
@app.route('/cb/get-installed-apps', methods=['GET'])
def get_installed_apps():
    """Get list of installed apps"""
    if not HAS_COFFEEBLACK:
        return jsonify({'success': False, 'error': 'CoffeeBlack SDK is not installed'})
    
    try:
        sdk = get_sdk()
        
        # Check if the SDK has the get_installed_apps method
        if hasattr(sdk, 'get_installed_apps'):
            apps = sdk.get_installed_apps()
            return jsonify({
                'success': True,
                'apps': apps
            })
        else:
            return jsonify({'success': False, 'error': 'SDK does not support get_installed_apps'})
        
    except Exception as e:
        print(f"Error getting installed apps: {str(e)}")
        return jsonify({'success': False, 'error': str(e)})


@app.route('/cb/compare-images', methods=['POST'])
def compare_images_endpoint():
    """Compare two images and return similarity metrics"""
    if not HAS_COFFEEBLACK:
        return jsonify({'success': False, 'error': 'CoffeeBlack SDK is not installed'})
    
    try:
        data = request.json
        if not data:
            return jsonify({'success': False, 'error': 'No data provided'})
        
        # Get image data
        image1_data = data.get('image1')
        image2_data = data.get('image2')
        image1_id = data.get('image1_id')
        image2_id = data.get('image2_id')
        normalize = data.get('normalize', True)
        
        # Process based on what was provided
        if image1_data and image2_data:
            # Both images provided as base64
            image1_bytes = base64.b64decode(image1_data.split(',')[1] if ',' in image1_data else image1_data)
            image2_bytes = base64.b64decode(image2_data.split(',')[1] if ',' in image2_data else image2_data)
            
            # Convert to OpenCV format
            image1 = cv2.imdecode(np.frombuffer(image1_bytes, np.uint8), cv2.IMREAD_COLOR)
            image2 = cv2.imdecode(np.frombuffer(image2_bytes, np.uint8), cv2.IMREAD_COLOR)
            
        elif image1_id and image2_id:
            # Use stored reference images
            if image1_id not in reference_images or image2_id not in reference_images:
                return jsonify({
                    'success': False, 
                    'error': f'One or both image IDs not found: {image1_id}, {image2_id}'
                })
                
            image1 = reference_images[image1_id]['image']
            image2 = reference_images[image2_id]['image']
            
        else:
            return jsonify({
                'success': False, 
                'error': 'Must provide either two image data strings or two valid image IDs'
            })
        
        # Perform comparison using SDK if available
        sdk = get_sdk()
        if hasattr(sdk, 'compare'):
            # Use the SDK's compare function
            try:
                result = run_async(sdk.compare(image1, image2, normalize=normalize))
                return jsonify({
                    'success': True,
                    'comparison': result
                })
            except Exception as e:
                print(f"SDK compare failed: {str(e)}, falling back to custom implementation")
                # Fall back to custom implementation
                pass
        
        # Fall back to custom implementation
        similarity = compare_images(image1, image2)
        
        return jsonify({
            'success': True,
            'similarity': similarity,
            'comparison': {
                'similarity': similarity,
                'cosine_similarity': similarity,
                'cosine_distance': 1.0 - similarity
            }
        })
        
    except Exception as e:
        print(f"Error comparing images: {str(e)}")
        return jsonify({'success': False, 'error': str(e)})


@app.route('/cb/swipe', methods=['POST'])
def swipe():
    """Perform a swipe action on the current screen"""
    if not HAS_COFFEEBLACK:
        return jsonify({'success': False, 'error': 'CoffeeBlack SDK is not installed'})
    
    try:
        data = request.json
        if not data or 'direction' not in data:
            return jsonify({'success': False, 'error': 'No direction provided'})
        
        direction = data['direction'].lower()
        if direction not in ['left', 'right', 'up', 'down']:
            return jsonify({'success': False, 'error': f'Invalid direction: {direction}'})
        
        sdk = get_sdk()
        
        # Try to use the swipe function if available
        if hasattr(sdk, 'swipe'):
            result = run_async(sdk.swipe(direction))
            return jsonify({
                'success': True,
                'message': f'Swiped {direction}',
                'result': str(result)
            })
        else:
            # Fall back to execute_action
            # For Tinder, we map directions to UI actions
            action_map = {
                'left': "Click on the red X button",  # Dislike
                'right': "Click on the green heart button",  # Like
                'up': "Click on the blue star button",  # Super Like
                'down': "Click on the back button"  # Go back
            }
            
            action = action_map.get(direction)
            result = run_async(sdk.execute_action(action))
            
            return jsonify({
                'success': True,
                'message': f'Executed action for {direction} swipe: {action}',
                'result': str(result)
            })
        
    except Exception as e:
        print(f"Error swiping: {str(e)}")
        return jsonify({'success': False, 'error': str(e)})


@app.route('/cb/start-tinder-loop', methods=['POST'])
def start_tinder_loop():
    """Start the Tinder automation loop"""
    global tinder_automation
    
    if not HAS_COFFEEBLACK:
        return jsonify({'success': False, 'error': 'CoffeeBlack SDK is not installed'})
    
    if tinder_automation['running']:
        return jsonify({'success': False, 'error': 'Tinder automation is already running'})
    
    try:
        data = request.json or {}
        
        # Update configuration from request if provided
        if data:
            if 'similarity_mode' in data:
                tinder_automation['config']['similarity_mode'] = data['similarity_mode']
            if 'max_swipes' in data:
                tinder_automation['config']['max_swipes'] = int(data['max_swipes'])
        
        # Initialize stats
        tinder_automation['stats'] = {
            'total_profiles': 0,
            'likes': 0,
            'dislikes': 0,
            'matches': 0,
            'start_time': time.time(),
            'end_time': None
        }
        
        # Set running state
        tinder_automation['running'] = True
        tinder_automation['paused'] = False
        
        # Start the automation in a separate thread
        threading.Thread(target=tinder_automation_loop, daemon=True).start()
        
        return jsonify({
            'success': True,
            'message': 'Tinder automation started',
            'config': tinder_automation['config']
        })
        
    except Exception as e:
        print(f"Error starting Tinder automation: {str(e)}")
        tinder_automation['running'] = False
        return jsonify({'success': False, 'error': str(e)})


@app.route('/cb/pause-tinder-loop', methods=['POST'])
def pause_tinder_loop():
    """Pause the Tinder automation loop"""
    global tinder_automation
    
    if not tinder_automation['running']:
        return jsonify({'success': False, 'error': 'Tinder automation is not running'})
    
    if tinder_automation['paused']:
        return jsonify({'success': False, 'error': 'Tinder automation is already paused'})
    
    try:
        tinder_automation['paused'] = True
        
        return jsonify({
            'success': True,
            'message': 'Tinder automation paused',
            'stats': tinder_automation['stats']
        })
        
    except Exception as e:
        print(f"Error pausing Tinder automation: {str(e)}")
        return jsonify({'success': False, 'error': str(e)})


@app.route('/cb/resume-tinder-loop', methods=['POST'])
def resume_tinder_loop():
    """Resume the Tinder automation loop"""
    global tinder_automation
    
    if not tinder_automation['running']:
        return jsonify({'success': False, 'error': 'Tinder automation is not running'})
    
    if not tinder_automation['paused']:
        return jsonify({'success': False, 'error': 'Tinder automation is not paused'})
    
    try:
        tinder_automation['paused'] = False
        
        return jsonify({
            'success': True,
            'message': 'Tinder automation resumed',
            'stats': tinder_automation['stats']
        })
        
    except Exception as e:
        print(f"Error resuming Tinder automation: {str(e)}")
        return jsonify({'success': False, 'error': str(e)})


@app.route('/cb/stop-tinder-loop', methods=['POST'])
def stop_tinder_loop():
    """Stop the Tinder automation loop"""
    global tinder_automation
    
    if not tinder_automation['running']:
        return jsonify({'success': False, 'error': 'Tinder automation is not running'})
    
    try:
        tinder_automation['running'] = False
        tinder_automation['paused'] = False
        tinder_automation['stats']['end_time'] = time.time()
        
        return jsonify({
            'success': True,
            'message': 'Tinder automation stopped',
            'stats': tinder_automation['stats']
        })
        
    except Exception as e:
        print(f"Error stopping Tinder automation: {str(e)}")
        return jsonify({'success': False, 'error': str(e)})


# Process screenshot to isolate profile area
def preprocess_screenshot(screenshot_np):
    """
    Process the screenshot to better isolate the profile content before comparison.
    Focuses on the center area of the image and applies additional preprocessing.
    """
    try:
        height, width = screenshot_np.shape[:2]
        
        # Crop the center area to focus on the profile
        # Remove top UI elements (20% from top), bottom UI elements (10% from bottom)
        # and some side margins (10% from each side)
        crop_top = int(height * 0.20)
        crop_bottom = int(height * 0.90)
        crop_left = int(width * 0.10)
        crop_right = int(width * 0.90)
        
        # Apply the crop
        cropped_img = screenshot_np[crop_top:crop_bottom, crop_left:crop_right]
        
        # Apply slight Gaussian blur to reduce noise (optional)
        blurred_img = cv2.GaussianBlur(cropped_img, (3, 3), 0)
        
        return blurred_img
    except Exception as e:
        print(f"Error preprocessing screenshot: {str(e)}")
        # Return original if processing fails
        return screenshot_np


# Tinder automation loop function
def tinder_automation_loop(reference_images_param, tinder_config):
    """Main function for automated Tinder swiping"""
    global tinder_automation, reference_images
    
    try:
        # Store the passed reference images
        if reference_images_param:
            reference_images = reference_images_param
        
        print(f"Starting Tinder automation loop with config: {tinder_config}")
        sdk = get_sdk()
        
        if sdk is None:
            print("Error: SDK is not available")
            tinder_automation['running'] = False
            return
        
        # Setup tinder_automation object with the config
        if not 'config' in tinder_automation:
            tinder_automation['config'] = {}
            
        # Update config from parameters
        tinder_automation['config']['max_swipes'] = tinder_config.get('max_swipes', 100)
        tinder_automation['config']['similarity_mode'] = tinder_config.get('similarity_mode', 'similar')
        
        # Initialize stats if needed
        if not 'stats' in tinder_automation:
            tinder_automation['stats'] = {
                'total_profiles': 0,
                'likes': 0,
                'dislikes': 0,
                'matches': 0,
                'start_time': time.time(),
                'end_time': None,
                'similarity_metrics': {
                    'likes_avg_similarity': 0.0,
                    'dislikes_avg_similarity': 0.0,
                    'total_avg_similarity': 0.0,
                    'max_similarity': 0.0,
                    'min_similarity': 1.0,
                    'similarity_history': []  # List of {profile_id, decision, similarity, reference_id}
                }
            }
            
        # Set running state
        tinder_automation['running'] = True
        tinder_automation['paused'] = False
        
        # Track progress
        swipe_count = 0
        max_swipes = tinder_automation['config']['max_swipes']
        threshold = tinder_automation['config']['similarity_thresholds'][tinder_automation['config']['similarity_mode']]
        
        # Open iPhone Mirroring app
        print("Opening iPhone Mirroring...")
        try:
            run_async(sdk.open_and_attach_to_app("iPhone Mirroring", wait_time=5.0))
            time.sleep(2)
        except Exception as e:
            print(f"Error opening iPhone Mirroring: {str(e)}")
            tinder_automation['running'] = False
            return
        
        # Navigate to Tinder
        print("Navigating to Tinder...")
        try:
            # Click on search
            run_async(sdk.execute_action("Click on Search"))
            time.sleep(1)
            
            # Type "Tinder"
            for char in "Tinder":
                run_async(sdk.press_key(char))
                time.sleep(0.1)
            time.sleep(1)
            
            # Click on Tinder icon
            run_async(sdk.execute_action("Click on the Tinder icon"))
            time.sleep(3)
            
            # Handle any initial popups or dialogs
            try:
                run_async(sdk.execute_action("Click on the X button or Close button if visible"))
            except:
                pass
        except Exception as e:
            print(f"Error navigating to Tinder: {str(e)}")
            tinder_automation['running'] = False
            return
        
        # Main swiping loop
        while tinder_automation['running'] and swipe_count < max_swipes:
            # Check if paused
            if tinder_automation['paused']:
                print("Automation paused, waiting...")
                time.sleep(1)
                continue
            
            print(f"Processing profile {swipe_count + 1}/{max_swipes}")
            
            # Take a screenshot of the current profile
            try:
                screenshot_bytes = run_async(sdk.get_screenshot())
                screenshot_np = cv2.imdecode(np.frombuffer(screenshot_bytes, np.uint8), cv2.IMREAD_COLOR)
                
                # Apply preprocessing to focus on the profile content
                processed_screenshot = preprocess_screenshot(screenshot_np)
                
                # Create debug directory if it doesn't exist
                debug_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'debug', 'screenshots')
                os.makedirs(debug_dir, exist_ok=True)
                
                # Save both original and processed screenshots for debugging
                debug_image_id = f"debug_profile_{swipe_count}"
                orig_debug_path = os.path.join(debug_dir, f"original_{int(time.time())}.png")
                proc_debug_path = os.path.join(debug_dir, f"processed_{int(time.time())}.png")
                cv2.imwrite(orig_debug_path, screenshot_np)
                cv2.imwrite(proc_debug_path, processed_screenshot)
                print(f"Screenshots saved to {debug_dir}")
                
                # Store in memory for possible later use
                reference_images[debug_image_id] = processed_screenshot
                
                # Compare with reference images to decide swipe direction
                best_match_score = 0
                best_match_id = None
                
                for img_id, img_data in reference_images.items():
                    # Skip debug images
                    if img_id.startswith("debug_"):
                        continue
                    
                    # Handle different formats of reference_images
                    reference_img = None
                    if isinstance(img_data, dict) and 'image' in img_data:
                        reference_img = img_data['image']
                    elif isinstance(img_data, np.ndarray):
                        # Direct numpy array (CV2 image)
                        reference_img = img_data
                    else:
                        print(f"Skipping reference image {img_id}: unknown format {type(img_data)}")
                        continue
                    
                    if reference_img is None:
                        print(f"Skipping reference image {img_id}: no valid image data")
                        continue
                        
                    similarity = compare_images(processed_screenshot, reference_img)
                    print(f"Similarity with reference {img_id}: {similarity:.2f}")
                    
                    if similarity > best_match_score:
                        best_match_score = similarity
                        best_match_id = img_id
                
                # Update overall similarity statistics
                metrics = tinder_automation['stats']['similarity_metrics']
                if 'total_avg_similarity' not in metrics:
                    metrics['total_avg_similarity'] = 0.0
                if 'max_similarity' not in metrics:
                    metrics['max_similarity'] = 0.0
                if 'min_similarity' not in metrics:
                    metrics['min_similarity'] = 1.0
                if 'similarity_history' not in metrics:
                    metrics['similarity_history'] = []
                    
                # Only update metrics if we have a valid similarity score
                if best_match_score > 0:
                    # Update total average
                    metrics['total_avg_similarity'] = ((metrics['total_avg_similarity'] * swipe_count) + best_match_score) / (swipe_count + 1) if swipe_count > 0 else best_match_score
                    
                    # Update max/min
                    if best_match_score > metrics['max_similarity']:
                        metrics['max_similarity'] = best_match_score
                    if best_match_score < metrics['min_similarity']:
                        metrics['min_similarity'] = best_match_score
                
                # Get the threshold based on the selected similarity mode
                similarity_mode = tinder_automation['config']['similarity_mode']
                threshold = tinder_automation['config']['similarity_thresholds'][similarity_mode]
                
                # Use the similarity score directly instead of inverting it
                print(f"Similarity score: {best_match_score:.2f}, Threshold: {threshold}")
                
                # Decide whether to swipe right (like) or left (pass) based on similarity
                if best_match_score >= threshold:
                    print(f"Match found! Similarity: {best_match_score:.2f} with {best_match_id}, swiping right")
                    run_async(sdk.execute_action("Click on the green heart button"))
                    tinder_automation['stats']['likes'] += 1
                    
                    # Update likes similarity average
                    likes_count = tinder_automation['stats']['likes']
                    metrics['likes_avg_similarity'] = ((metrics['likes_avg_similarity'] * (likes_count - 1)) + best_match_score) / likes_count if likes_count > 1 else best_match_score
                    
                    # Add to history (store only the original score)
                    decision_record = {
                        'profile_id': debug_image_id,
                        'decision': 'like',
                        'similarity': best_match_score,
                        'reference_id': best_match_id
                    }
                    metrics['similarity_history'].append(decision_record)
                    
                    # Also update recent_decisions in the main tinder_automation object
                    if 'recent_decisions' not in tinder_automation:
                        tinder_automation['recent_decisions'] = []
                        
                    # Add screenshot to the decision record
                    decision_record_with_image = decision_record.copy()
                    
                    # Convert screenshot to base64 for frontend display
                    _, buffer = cv2.imencode('.jpg', processed_screenshot)
                    screenshot_base64 = base64.b64encode(buffer).decode('utf-8')
                    decision_record_with_image['screenshot'] = f"data:image/jpeg;base64,{screenshot_base64}"
                    
                    # Add reference image if available
                    if best_match_id and best_match_id in reference_images:
                        reference_img = reference_images[best_match_id]
                        _, buffer = cv2.imencode('.jpg', reference_img)
                        reference_base64 = base64.b64encode(buffer).decode('utf-8')
                        decision_record_with_image['reference_image'] = f"data:image/jpeg;base64,{reference_base64}"
                    
                    # Add to recent decisions (keep only last 10)
                    tinder_automation['recent_decisions'].insert(0, decision_record_with_image)
                    if len(tinder_automation['recent_decisions']) > 10:
                        tinder_automation['recent_decisions'] = tinder_automation['recent_decisions'][:10]
                    
                    # Check for match popup after right swipe
                    time.sleep(1)
                    match_check = run_async(sdk.see("It's a Match! or Keep Swiping button", wait=True, timeout=2.0))
                    if match_check.get('matches', False):
                        print("Match detected!")
                        tinder_automation['stats']['matches'] += 1
                        # Click "Keep Swiping"
                        run_async(sdk.execute_action("Click on Keep Swiping button"))
                        time.sleep(1)
                else:
                    print(f"No match. Similarity: {best_match_score:.2f}, swiping left")
                    run_async(sdk.execute_action("Click on the red X button"))
                    tinder_automation['stats']['dislikes'] += 1
                    
                    # Update dislikes similarity average
                    dislikes_count = tinder_automation['stats']['dislikes']
                    metrics['dislikes_avg_similarity'] = ((metrics['dislikes_avg_similarity'] * (dislikes_count - 1)) + best_match_score) / dislikes_count if dislikes_count > 1 else best_match_score
                    
                    # Add to history (store only the original score)
                    decision_record = {
                        'profile_id': debug_image_id,
                        'decision': 'dislike',
                        'similarity': best_match_score,
                        'reference_id': best_match_id
                    }
                    metrics['similarity_history'].append(decision_record)
                    
                    # Add to recent_decisions in the main tinder_automation object
                    if 'recent_decisions' not in tinder_automation:
                        tinder_automation['recent_decisions'] = []
                        
                    # Add screenshot to the decision record
                    decision_record_with_image = decision_record.copy()
                    
                    # Convert screenshot to base64 for frontend display
                    _, buffer = cv2.imencode('.jpg', processed_screenshot)
                    screenshot_base64 = base64.b64encode(buffer).decode('utf-8')
                    decision_record_with_image['screenshot'] = f"data:image/jpeg;base64,{screenshot_base64}"
                    
                    # Add reference image if available
                    if best_match_id and best_match_id in reference_images:
                        reference_img = reference_images[best_match_id]
                        _, buffer = cv2.imencode('.jpg', reference_img)
                        reference_base64 = base64.b64encode(buffer).decode('utf-8')
                        decision_record_with_image['reference_image'] = f"data:image/jpeg;base64,{reference_base64}"
                    
                    # Add to recent decisions (keep only last 10)
                    tinder_automation['recent_decisions'].insert(0, decision_record_with_image)
                    if len(tinder_automation['recent_decisions']) > 10:
                        tinder_automation['recent_decisions'] = tinder_automation['recent_decisions'][:10]
                
                # Update stats
                swipe_count += 1
                tinder_automation['stats']['total_profiles'] = swipe_count
                
                # Wait between swipes - fixed delay of 0.5 seconds
                time.sleep(0.5)
                
            except Exception as e:
                print(f"Error processing profile: {str(e)}")
                # Try to continue with the next profile
                time.sleep(2)
        
        print(f"Tinder automation completed. Processed {swipe_count} profiles.")
        tinder_automation['stats']['end_time'] = time.time()
        tinder_automation['running'] = False
        
    except Exception as e:
        print(f"Error in Tinder automation loop: {str(e)}")
        tinder_automation['running'] = False


@app.route('/cb/tinder-stats', methods=['GET'])
def get_tinder_stats():
    """Get detailed Tinder automation statistics"""
    try:
        # Calculate additional statistics
        stats = tinder_automation['stats']
        metrics = stats['similarity_metrics']
        
        # Get the current similarity mode and threshold
        similarity_mode = tinder_automation['config']['similarity_mode']
        current_threshold = tinder_automation['config']['similarity_thresholds'][similarity_mode]
        
        # Count swipes by direction
        like_count = stats['likes']
        dislike_count = stats['dislikes']
        total_swipes = like_count + dislike_count
        
        # Calculate percentages
        like_percentage = (like_count / total_swipes * 100) if total_swipes > 0 else 0
        dislike_percentage = (dislike_count / total_swipes * 100) if total_swipes > 0 else 0
        
        # Calculate running time
        if stats['start_time']:
            end_time = stats['end_time'] or time.time()
            running_time = end_time - stats['start_time']
            
            # Format as hours, minutes, seconds
            hours = int(running_time // 3600)
            minutes = int((running_time % 3600) // 60)
            seconds = int(running_time % 60)
            formatted_time = f"{hours}h {minutes}m {seconds}s"
        else:
            running_time = 0
            formatted_time = "0h 0m 0s"
        
        # Create response data
        response_data = {
            'success': True,
            'running': tinder_automation['running'],
            'paused': tinder_automation['paused'],
            'config': tinder_automation['config'],
            'current_threshold': current_threshold,
            'stats': {
                'total_profiles': total_swipes,
                'likes': like_count,
                'dislikes': dislike_count,
                'matches': stats['matches'],
                'like_percentage': round(like_percentage, 1),
                'dislike_percentage': round(dislike_percentage, 1),
                'running_time': {
                    'seconds': running_time,
                    'formatted': formatted_time
                }
            },
            'similarity_metrics': {
                'overall_avg': round(metrics['total_avg_similarity'], 3),
                'likes_avg': round(metrics['likes_avg_similarity'], 3),
                'dislikes_avg': round(metrics['dislikes_avg_similarity'], 3),
                'max_similarity': round(metrics['max_similarity'], 3),
                'min_similarity': round(metrics['min_similarity'], 3)
            }
        }
        
        # Use tinder_automation['recent_decisions'] instead of metrics['similarity_history']
        # This includes the screenshot and reference image data needed by the frontend
        if 'recent_decisions' in tinder_automation and tinder_automation['recent_decisions']:
            response_data['recent_decisions'] = tinder_automation['recent_decisions']
        else:
            # Fallback to history if no recent_decisions available
            recent_decisions = metrics['similarity_history'][-10:] if metrics['similarity_history'] else []
            response_data['recent_decisions'] = recent_decisions
        
        return jsonify(response_data)
        
    except Exception as e:
        print(f"Error getting Tinder stats: {str(e)}")
        return jsonify({'success': False, 'error': str(e)})


@app.route('/cb/cleanup-resources', methods=['POST'])
def cleanup_resources():
    """
    Clean up temporary files and resources
    """
    try:
        print("Cleaning up resources...")
        
        # Define directories to clean
        debug_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'debug')
        temp_files = []
        
        # Clean up debug screenshots
        if os.path.exists(debug_dir):
            print(f"Cleaning debug directory: {debug_dir}")
            for file in os.listdir(debug_dir):
                if file.startswith(('original-', 'cropped-')):
                    file_path = os.path.join(debug_dir, file)
                    try:
                        os.remove(file_path)
                        temp_files.append(file)
                    except Exception as e:
                        print(f"Error removing file {file_path}: {e}")
        
        # Clean up any temporary reference images
        temp_refs = []
        if os.path.exists(REFERENCE_ELEMENTS_DIR):
            print(f"Cleaning reference elements directory: {REFERENCE_ELEMENTS_DIR}")
            # Only remove temporary references more than 1 hour old
            current_time = time.time()
            for file in os.listdir(REFERENCE_ELEMENTS_DIR):
                if file.startswith('temp_'):
                    file_path = os.path.join(REFERENCE_ELEMENTS_DIR, file)
                    # Check file age
                    file_age = current_time - os.path.getmtime(file_path)
                    if file_age > 3600:  # 1 hour in seconds
                        try:
                            os.remove(file_path)
                            temp_refs.append(file)
                        except Exception as e:
                            print(f"Error removing file {file_path}: {e}")
        
        return jsonify({
            'success': True,
            'message': 'Resources cleaned up successfully',
            'details': {
                'temp_files_removed': len(temp_files),
                'temp_refs_removed': len(temp_refs)
            }
        })
    except Exception as e:
        print(f"Error cleaning up resources: {e}")
        return jsonify({
            'success': False,
            'error': f"Failed to clean up resources: {str(e)}"
        })


if __name__ == '__main__':
    # Load any saved images
    load_saved_images()
    
    # Start the Flask server
    print("Starting Python server...")
    app.run(
        host='0.0.0.0',  # Allow external connections
        port=5001,  # Changed from 5000 to avoid AirPlay conflicts
        debug=False,
        threaded=True,
        use_reloader=False  # Disable reloader to prevent duplicate processes
    ) 