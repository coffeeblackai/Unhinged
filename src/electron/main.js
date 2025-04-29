const { app, BrowserWindow, ipcMain } = require('electron');
const path = require('path');
const isDev = require('electron-is-dev');
const axios = require('axios');
const { spawn } = require('child_process');
const fs = require('fs');
const FormData = require('form-data');

let mainWindow;
let pythonProcess;
const PYTHON_SERVER_PORT = 5001;
const API_BASE_URL = `http://127.0.0.1:${PYTHON_SERVER_PORT}`;

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 390,
    height: 880,
    minWidth: 375,
    minHeight: 600,
    maxWidth: 414,
    maxHeight: 880,
    webPreferences: {
      nodeIntegration: true,
      contextIsolation: false,
    },
    title: 'Unhinged',
    backgroundColor: '#f5f5f7',
    titleBarStyle: 'hidden',
    titleBarOverlay: {
      color: '#f5f5f7',
      symbolColor: '#000'
    },
    icon: path.join(__dirname, 'logo-white-bg.png')
  });

  mainWindow.loadFile(path.join(__dirname, '../electron/index.html'));

  // Comment out the auto-opening of DevTools
  // if (isDev) {
  //   mainWindow.webContents.openDevTools();
  // }

  mainWindow.on('closed', () => {
    mainWindow = null;
  });
}

// Function to install Python dependencies
function installPythonDependencies() {
  return new Promise((resolve, reject) => {
    console.log('Installing Python dependencies...');
    
    const requirementsPath = path.join(__dirname, '../../src/python/requirements.txt');
    if (!fs.existsSync(requirementsPath)) {
      console.error('requirements.txt not found at:', requirementsPath);
      return resolve(false);
    }
    
    const pipProcess = spawn('pip', ['install', '-r', requirementsPath]);
    
    pipProcess.stdout.on('data', (data) => {
      console.log(`pip: ${data}`);
    });
    
    pipProcess.stderr.on('data', (data) => {
      console.error(`pip error: ${data}`);
    });
    
    pipProcess.on('close', (code) => {
      if (code === 0) {
        console.log('Python dependencies installed successfully');
        resolve(true);
      } else {
        console.error(`pip process exited with code ${code}`);
        resolve(false);
      }
    });
  });
}

function startPythonServer() {
  // Determine paths based on whether in dev or production mode
  const pythonPath = isDev 
    ? path.join(__dirname, '../../src/python/server.py') 
    : path.join(process.resourcesPath, 'python/server.py');

  console.log('Starting Python server from:', pythonPath);

  if (!fs.existsSync(pythonPath)) {
    console.error('Python server file not found at:', pythonPath);
    return;
  }

  // Use python3 if available, otherwise fallback to python
  let pythonCommand = 'python3';
  try {
    spawn(pythonCommand, ['--version']);
  } catch (e) {
    pythonCommand = 'python';
  }

  console.log(`Using Python command: ${pythonCommand}`);
  
  // Use system environment without modifying PYTHONPATH
  const env = { ...process.env };

  // Add CoffeeBlack API key if available in settings
  const apiKey = global.coffeeBlackApiKey || '';
  if (apiKey) {
    console.log('Using CoffeeBlack API key from settings');
    env.COFFEEBLACK_API_KEY = apiKey;
  }

  // Start Python with our custom environment
  pythonProcess = spawn(pythonCommand, [pythonPath], { env });

  pythonProcess.stdout.on('data', (data) => {
    console.log(`Python server: ${data}`);
  });

  pythonProcess.stderr.on('data', (data) => {
    console.error(`Python server error: ${data}`);
  });

  pythonProcess.on('close', (code) => {
    console.log(`Python server exited with code ${code}`);
  });
  
  pythonProcess.on('error', (err) => {
    console.error(`Failed to start Python server: ${err.message}`);
    
    // Notify the renderer process that Python startup failed
    if (mainWindow) {
      mainWindow.webContents.send('python-server-error', { 
        error: err.message 
      });
    }
  });
}

app.whenReady().then(async () => {
  // Create white background icon
  await createWhiteBackgroundIcon();

  // Skip Python dependencies installation, we'll use bundled packages instead
  // await installPythonDependencies();
  
  // Start the Python server
  startPythonServer();
  
  // Set dock icon for macOS
  if (process.platform === 'darwin') {
    const iconPath = path.join(__dirname, 'logo-white-bg.png');
    app.dock.setIcon(iconPath);
  }
  
  createWindow();

  // Wait for server to start - increased delay to 5 seconds
  setTimeout(() => {
    // First try a simple ping to test connectivity
    console.log('Testing basic server connectivity...');
    axios.get(`${API_BASE_URL}/ping`)
      .then(response => {
        console.log('Server ping successful:', response.data);
        
        // If ping works, try the regular status
        console.log('Testing status endpoint...');
        return axios.get(`${API_BASE_URL}/status`);
      })
      .then(response => {
        console.log('Status endpoint successful:', response.data);
        
        // Finally try the CoffeeBlack status
        console.log('Testing CoffeeBlack status...');
        return axios.get(`${API_BASE_URL}/cb/status`);
      })
      .then(response => {
        console.log('CoffeeBlack status successful:', response.data);
      })
      .catch(error => {
        console.error('Server connection test failed:', error.message);
        if (error.response) {
          console.error('Response data:', error.response.data);
          console.error('Response status:', error.response.status);
        } else if (error.request) {
          console.error('No response received, request:', error.request);
        }
      });
  }, 5000);

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') {
    app.quit();
  }
});

app.on('before-quit', () => {
  if (pythonProcess) {
    pythonProcess.kill();
  }
});

// IPC handlers for Tinder automation
ipcMain.handle('start-tinder-automation', async (event, params) => {
  try {
    console.log('Starting Tinder automation with params:', params);
    const response = await axios.post(`${API_BASE_URL}/start-tinder`, params);
    return response.data;
  } catch (error) {
    console.error('Failed to start Tinder automation:', error.message);
    return { success: false, error: error.message };
  }
});

ipcMain.handle('pause-tinder-automation', async () => {
  try {
    const response = await axios.post(`${API_BASE_URL}/cb/pause-tinder-loop`);
    return response.data;
  } catch (error) {
    console.error('Failed to pause Tinder automation:', error.message);
    return { success: false, error: error.message };
  }
});

ipcMain.handle('resume-tinder-automation', async () => {
  try {
    const response = await axios.post(`${API_BASE_URL}/cb/resume-tinder-loop`);
    return response.data;
  } catch (error) {
    console.error('Failed to resume Tinder automation:', error.message);
    return { success: false, error: error.message };
  }
});

ipcMain.handle('stop-tinder-automation', async () => {
  try {
    const response = await axios.post(`${API_BASE_URL}/stop-tinder`);
    return response.data;
  } catch (error) {
    console.error('Failed to stop Tinder automation:', error.message);
    return { success: false, error: error.message };
  }
});

ipcMain.handle('upload-reference-image', async (event, imageData) => {
  try {
    const response = await axios.post(`${API_BASE_URL}/upload-image`, { image: imageData });
    return response.data;
  } catch (error) {
    console.error('Failed to upload image:', error.message);
    return { success: false, error: error.message };
  }
});

// New IPC handler for uploading reference element files
ipcMain.handle('upload-reference-element-file', async (event, { filename, fileData }) => {
  try {
    // Extract base64 data
    const base64Data = fileData.split(',')[1];
    const buffer = Buffer.from(base64Data, 'base64');
    
    // Create a temporary file path
    const tempPath = path.join(app.getPath('temp'), filename);
    
    // Write the file to disk
    fs.writeFileSync(tempPath, buffer);
    
    // Create form data 
    const form = new FormData();
    form.append('file', fs.createReadStream(tempPath));
    
    // Upload the file
    const response = await axios.post(`${API_BASE_URL}/cb/upload-reference-element`, form, {
      headers: {
        ...form.getHeaders()
      }
    });
    
    // Clean up the temporary file
    fs.unlinkSync(tempPath);
    
    return response.data;
  } catch (error) {
    console.error('Failed to upload reference element:', error.message);
    return { success: false, error: error.message };
  }
});

// Helper function to add default headers and handle errors
const makeApiRequest = async (method, endpoint, data = null) => {
  try {
    console.log(`makeApiRequest: ${method.toUpperCase()} ${endpoint}`);
    
    const config = {
      headers: {
        'Content-Type': 'application/json',
        'Accept': 'application/json'
      }
    };
    
    console.log(`Request config:`, config);
    
    let response;
    if (method === 'get') {
      // Special case for /cb/status endpoint
      if (endpoint === '/cb/status') {
        console.log('Using direct axios call for /cb/status');
        response = await axios.get(`${API_BASE_URL}${endpoint}`);
      } else {
        response = await axios.get(`${API_BASE_URL}${endpoint}`, config);
      }
    } else if (method === 'post') {
      response = await axios.post(`${API_BASE_URL}${endpoint}`, data, config);
    }
    
    console.log(`Response received for ${endpoint}:`, response.status);
    return response.data;
  } catch (error) {
    console.error(`API request failed: ${endpoint}`, error.message);
    if (error.response) {
      console.error('Response data:', error.response.data);
      console.error('Response status:', error.response.status);
    }
    return { success: false, error: error.message };
  }
};

// New IPC handlers for CoffeeBlack SDK features
ipcMain.handle('cb-status', async () => {
  console.log('Direct cb-status call');
  try {
    const response = await axios.get(`${API_BASE_URL}/cb/status`);
    console.log('Direct cb-status response:', response.status);
    return response.data;
  } catch (error) {
    console.error('Direct cb-status error:', error.message);
    if (error.response) {
      console.error('Response data:', error.response.data);
      console.error('Response status:', error.response.status);
    }
    return { success: false, error: error.message };
  }
});

ipcMain.handle('cb-open-app', async (event, params) => {
  return await makeApiRequest('post', '/cb/open-app', params);
});

ipcMain.handle('cb-execute-action', async (event, params) => {
  return await makeApiRequest('post', '/cb/execute-action', params);
});

ipcMain.handle('cb-press-key', async (event, params) => {
  return await makeApiRequest('post', '/cb/press-key', params);
});

ipcMain.handle('cb-see', async (event, params) => {
  return await makeApiRequest('post', '/cb/see', params);
});

ipcMain.handle('cb-screenshot', async () => {
  return await makeApiRequest('get', '/cb/screenshot');
});

ipcMain.handle('cb-navigate-url', async (event, params) => {
  return await makeApiRequest('post', '/cb/navigate-url', params);
});

// New IPC handlers for generic API calls
ipcMain.handle('api-get', async (event, { endpoint }) => {
  console.log(`Processing GET ${endpoint}`);
  try {
    const url = `${API_BASE_URL}${endpoint}`;
    console.log(`GET request to ${url}`);
    
    let response;
    
    // Special case for /cb/status endpoint
    if (endpoint === '/cb/status') {
      console.log('Using direct axios call for api-get to /cb/status');
      response = await axios.get(url);
    } else {
      response = await axios.get(url, {
        headers: {
          'Content-Type': 'application/json',
          'Accept': 'application/json'
        }
      });
    }
    
    console.log(`GET ${endpoint} response status:`, response.status);
    return response.data;
  } catch (error) {
    console.error(`GET ${endpoint} failed:`, error.message);
    
    // Detailed error logging
    if (error.response) {
      console.error('Response status:', error.response.status);
      console.error('Response headers:', error.response.headers);
      console.error('Response data:', error.response.data);
    } else if (error.request) {
      console.error('No response received, request:', error.request);
    }
    
    return { success: false, error: error.message };
  }
});

ipcMain.handle('api-post', async (event, { endpoint, data }) => {
  console.log(`Processing POST ${endpoint}`);
  try {
    const url = `${API_BASE_URL}${endpoint}`;
    console.log(`POST request to ${url} with data:`, data);
    
    const response = await axios.post(url, data, {
      headers: {
        'Content-Type': 'application/json',
        'Accept': 'application/json'
      }
    });
    
    console.log(`POST ${endpoint} response status:`, response.status);
    return response.data;
  } catch (error) {
    console.error(`POST ${endpoint} failed:`, error.message);
    
    // Detailed error logging
    if (error.response) {
      console.error('Response status:', error.response.status);
      console.error('Response headers:', error.response.headers);
      console.error('Response data:', error.response.data);
    } else if (error.request) {
      console.error('No response received, request:', error.request);
    }
    
    return { success: false, error: error.message };
  }
});

// Tinder automation IPC handlers
ipcMain.handle('cb-get-installed-apps', async () => {
  console.log('Getting installed apps...');
  try {
    const response = await axios.get(`${API_BASE_URL}/cb/get-installed-apps`);
    console.log('Installed apps response:', response.status);
    return response.data;
  } catch (error) {
    console.error('Error getting installed apps:', error.message);
    if (error.response) {
      console.error('Response data:', error.response.data);
      console.error('Response status:', error.response.status);
    }
    return { success: false, error: error.message };
  }
});


ipcMain.handle('cb-swipe', async (event, { direction }) => {
  console.log(`Swiping ${direction}...`);
  try {
    const response = await axios.post(`${API_BASE_URL}/cb/swipe`, { direction });
    console.log('Swipe response:', response.status);
    return response.data;
  } catch (error) {
    console.error('Error swiping:', error.message);
    if (error.response) {
      console.error('Response data:', error.response.data);
      console.error('Response status:', error.response.status);
    }
    return { success: false, error: error.message };
  }
});

ipcMain.handle('cb-start-tinder-loop', async (event, config) => {
  console.log('Starting Tinder automation loop with config:', config);
  try {
    const response = await axios.post(`${API_BASE_URL}/cb/start-tinder-loop`, config);
    console.log('Start Tinder loop response:', response.status);
    return response.data;
  } catch (error) {
    console.error('Error starting Tinder loop:', error.message);
    if (error.response) {
      console.error('Response data:', error.response.data);
      console.error('Response status:', error.response.status);
    }
    return { success: false, error: error.message };
  }
});

ipcMain.handle('cb-pause-tinder-loop', async () => {
  console.log('Pausing Tinder automation loop...');
  try {
    const response = await axios.post(`${API_BASE_URL}/cb/pause-tinder-loop`);
    console.log('Pause Tinder loop response:', response.status);
    return response.data;
  } catch (error) {
    console.error('Error pausing Tinder loop:', error.message);
    if (error.response) {
      console.error('Response data:', error.response.data);
      console.error('Response status:', error.response.status);
    }
    return { success: false, error: error.message };
  }
});

ipcMain.handle('cb-resume-tinder-loop', async () => {
  console.log('Resuming Tinder automation loop...');
  try {
    const response = await axios.post(`${API_BASE_URL}/cb/resume-tinder-loop`);
    console.log('Resume Tinder loop response:', response.status);
    return response.data;
  } catch (error) {
    console.error('Error resuming Tinder loop:', error.message);
    if (error.response) {
      console.error('Response data:', error.response.data);
      console.error('Response status:', error.response.status);
    }
    return { success: false, error: error.message };
  }
});

ipcMain.handle('cb-stop-tinder-loop', async () => {
  console.log('Stopping Tinder automation loop...');
  try {
    const response = await axios.post(`${API_BASE_URL}/cb/stop-tinder-loop`);
    console.log('Stop Tinder loop response:', response.status);
    return response.data;
  } catch (error) {
    console.error('Error stopping Tinder loop:', error.message);
    if (error.response) {
      console.error('Response data:', error.response.data);
      console.error('Response status:', error.response.status);
    }
    return { success: false, error: error.message };
  }
});

ipcMain.handle('cb-get-tinder-stats', async () => {
  console.log('Getting Tinder statistics...');
  try {
    const response = await axios.get(`${API_BASE_URL}/cb/tinder-stats`);
    console.log('Tinder stats response:', response.status);
    
    // Log recent decisions information for debugging
    if (response.data && response.data.recent_decisions) {
      const decisions = response.data.recent_decisions;
      console.log(`Received ${decisions.length} recent decisions`);
      
      // Log details about the most recent decision if available
      if (decisions.length > 0) {
        const latestDecision = decisions[0];
        console.log(`Latest decision: ${latestDecision.decision} with similarity ${latestDecision.similarity}`);
        console.log(`Decision has image data: ${!!latestDecision.screenshot}, reference image: ${!!latestDecision.reference_image}`);
      }
    } else {
      console.log('No recent decisions in response');
    }
    
    return response.data;
  } catch (error) {
    console.error('Error getting Tinder statistics:', error.message);
    if (error.response) {
      console.error('Response data:', error.response.data);
      console.error('Response status:', error.response.status);
    }
    return { success: false, error: error.message };
  }
});

// Add missing handlers for the mobile-UI version
ipcMain.handle('cb-start-tinder', async (event, config) => {
  console.log('Starting Tinder automation...', config);
  try {
    const response = await axios.post(`${API_BASE_URL}/start-tinder`, config);
    console.log('Start Tinder response:', response.status);
    return response.data;
  } catch (error) {
    console.error('Error starting Tinder automation:', error.message);
    if (error.response) {
      console.error('Response data:', error.response.data);
      console.error('Response status:', error.response.status);
    }
    return { success: false, error: error.message };
  }
});

ipcMain.handle('cb-pause-tinder', async () => {
  console.log('Pausing Tinder automation...');
  try {
    const response = await axios.post(`${API_BASE_URL}/cb/pause-tinder-loop`);
    console.log('Pause Tinder response:', response.status);
    return response.data;
  } catch (error) {
    console.error('Error pausing Tinder automation:', error.message);
    if (error.response) {
      console.error('Response data:', error.response.data);
      console.error('Response status:', error.response.status);
    }
    return { success: false, error: error.message };
  }
});

ipcMain.handle('cb-resume-tinder', async () => {
  console.log('Resuming Tinder automation...');
  try {
    const response = await axios.post(`${API_BASE_URL}/cb/resume-tinder-loop`);
    console.log('Resume Tinder response:', response.status);
    return response.data;
  } catch (error) {
    console.error('Error resuming Tinder automation:', error.message);
    if (error.response) {
      console.error('Response data:', error.response.data);
      console.error('Response status:', error.response.status);
    }
    return { success: false, error: error.message };
  }
});

ipcMain.handle('cb-stop-tinder', async () => {
  console.log('Stopping Tinder automation...');
  try {
    const response = await axios.post(`${API_BASE_URL}/stop-tinder`);
    console.log('Stop Tinder response:', response.status);
    return response.data;
  } catch (error) {
    console.error('Error stopping Tinder automation:', error.message);
    if (error.response) {
      console.error('Response data:', error.response.data);
      console.error('Response status:', error.response.status);
    }
    return { success: false, error: error.message };
  }
});

ipcMain.handle('cb-compare-images', async (event, { image1, image2, image1Id, image2Id, normalize }) => {
  console.log('Comparing images...');
  try {
    const payload = {};
    
    // Add images or image IDs based on what's provided
    if (image1) payload.image1 = image1;
    if (image2) payload.image2 = image2;
    if (image1Id) payload.image1_id = image1Id;
    if (image2Id) payload.image2_id = image2Id;
    if (normalize !== undefined) payload.normalize = normalize;
    
    const response = await axios.post(`${API_BASE_URL}/cb/compare-images`, payload);
    console.log('Image comparison response:', response.status);
    return response.data;
  } catch (error) {
    console.error('Error comparing images:', error.message);
    if (error.response) {
      console.error('Response data:', error.response.data);
      console.error('Response status:', error.response.status);
    }
    return { success: false, error: error.message };
  }
});

// New IPC handler for cleaning up resources
ipcMain.handle('cb-cleanup-resources', async () => {
  try {
    const response = await axios.post(`${API_BASE_URL}/cb/cleanup-resources`);
    return response.data;
  } catch (error) {
    console.error('Failed to clean up resources:', error.message);
    return { success: false, error: error.message };
  }
});

// Simpler image processing function using basic Buffer manipulation
function cropTinderProfile(imageData) {
  return new Promise((resolve, reject) => {
    try {
      // Just extract base64 data
      const base64Data = imageData.replace(/^data:image\/\w+;base64,/, '');
      
      // For debugging - save original image
      saveDebugImages(imageData, imageData);
      
      // Simply return the original image for now
      // In a production app, you might want to implement a simple
      // buffer manipulation approach or use a lighter image library
      resolve(imageData);
    } catch (error) {
      console.error('Error processing image:', error);
      // If processing fails, return the original image
      resolve(imageData);
    }
  });
}

function saveDebugImages(originalImageData, croppedImageData) {
  try {
    const timestamp = new Date().toISOString().replace(/[:.]/g, '-');
    
    // Create debug directory if it doesn't exist
    const debugDir = path.join(__dirname, '../../debug');
    if (!fs.existsSync(debugDir)) {
      fs.mkdirSync(debugDir, { recursive: true });
    }
    
    // Save original image
    const originalPath = path.join(debugDir, `original-${timestamp}.jpg`);
    const originalBase64 = originalImageData.replace(/^data:image\/\w+;base64,/, '');
    fs.writeFileSync(originalPath, Buffer.from(originalBase64, 'base64'));
    
    // Save cropped image
    const croppedPath = path.join(debugDir, `cropped-${timestamp}.jpg`);
    const croppedBase64 = croppedImageData.replace(/^data:image\/\w+;base64,/, '');
    fs.writeFileSync(croppedPath, Buffer.from(croppedBase64, 'base64'));
    
    console.log(`Debug images saved: original and cropped for ${timestamp}`);
  } catch (error) {
    console.error('Error saving debug images:', error);
  }
}

// Add IPC handler for the image cropping functionality
ipcMain.handle('crop-tinder-profile', async (event, imageData) => {
  try {
    console.log('Cropping Tinder profile image...');
    const croppedImage = await cropTinderProfile(imageData);
    return { success: true, croppedImage };
  } catch (error) {
    console.error('Failed to crop image:', error.message);
    return { success: false, error: error.message, originalImage: imageData };
  }
});

// Function to create a white background version of the logo
function createWhiteBackgroundIcon() {
  return new Promise((resolve, reject) => {
    try {
      const whiteLogoPath = path.join(__dirname, 'logo-white-bg.png');

      // Check if the white background logo already exists
      if (fs.existsSync(whiteLogoPath)) {
        console.log('White background logo already exists');
        return resolve();
      }

      console.log('Using existing logo file as is');
      resolve();
    } catch (error) {
      console.error('Error creating white background logo:', error);
      resolve(); // Continue even if there's an error
    }
  });
}

// Add API key handling
ipcMain.handle('set-coffeeblack-api-key', async (event, apiKey) => {
  try {
    console.log('Setting CoffeeBlack API key');
    // Store globally for server restart
    global.coffeeBlackApiKey = apiKey;
    
    // Send to running Python server
    const response = await axios.post(`${API_BASE_URL}/cb/set-api-key`, { api_key: apiKey });
    return response.data;
  } catch (error) {
    console.error('Failed to set CoffeeBlack API key:', error.message);
    return { success: false, error: error.message };
  }
});

ipcMain.handle('get-coffeeblack-api-key-status', async () => {
  try {
    // Check if API key is set in Python server
    const response = await axios.get(`${API_BASE_URL}/cb/status`);
    return { 
      success: true, 
      apiKeySet: response.data.api_key_set || false
    };
  } catch (error) {
    console.error('Failed to get CoffeeBlack API key status:', error.message);
    return { success: false, error: error.message };
  }
}); 