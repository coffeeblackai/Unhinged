/**
 * CoffeeBlack API Wrapper
 * 
 * This module provides wrapper functions for the CoffeeBlack SDK functionality
 * exposed by the Python backend through REST API endpoints.
 */

const { ipcRenderer } = require('electron');

const API_BASE_URL = 'http://localhost:5001';

// Generic API call function with detailed error handling
async function callApi(method, endpoint, data = null) {
  console.log(`Calling ${method.toUpperCase()} ${endpoint} with data:`, data);
  
  try {
    const url = `${API_BASE_URL}${endpoint}`;
    console.log(`Full URL: ${url}`);
    
    // Use IPC calls instead of direct fetch for better error handling
    let response;
    if (method.toLowerCase() === 'get') {
      response = await ipcRenderer.invoke('api-get', { endpoint });
    } else if (method.toLowerCase() === 'post') {
      response = await ipcRenderer.invoke('api-post', { endpoint, data });
    }
    
    console.log(`Response for ${endpoint}:`, response);
    
    if (!response.success && response.error) {
      throw new Error(response.error);
    }
    
    return response;
  } catch (error) {
    console.error(`Error calling ${endpoint}:`, error);
    throw error;
  }
}

/**
 * CoffeeBlack API wrapper class
 */
class CoffeeBlackApi {
  /**
   * Check if CoffeeBlack SDK is available
   * @returns {Promise<Object>} Status object with availability info
   */
  async getStatus() {
    try {
      console.log('Checking CoffeeBlack SDK status...');
      return await callApi('get', '/cb/status');
    } catch (error) {
      console.error('Failed to get CoffeeBlack status:', error);
      throw error;
    }
  }

  /**
   * Open an application
   * @param {string} appName - The name of the application to open
   * @param {number} waitTime - Time to wait after opening (in seconds)
   * @returns {Promise<Object>} Result of the operation
   */
  async openApp(appName, waitTime = 2.0) {
    return await callApi('post', '/cb/open-app', { 
      app_name: appName, 
      wait_time: waitTime 
    });
  }

  /**
   * Execute an action using natural language instructions
   * @param {string} query - Natural language instruction of what to do
   * @param {string} referenceElement - Optional filename of reference element image
   * @param {number} elementsConf - Confidence threshold for element detection
   * @param {number} containerConf - Confidence threshold for container detection
   * @returns {Promise<Object>} Result of the operation
   */
  async executeAction(query, referenceElement = null, elementsConf = 0.4, containerConf = 0.3) {
    return await callApi('post', '/cb/execute-action', { 
      query, 
      reference_element: referenceElement,
      elements_conf: elementsConf,
      container_conf: containerConf
    });
  }

  /**
   * Press a keyboard key
   * @param {string} key - Key to press (e.g., 'enter', 'tab', etc.)
   * @returns {Promise<Object>} Result of the operation
   */
  async pressKey(key) {
    return await callApi('post', '/cb/press-key', { key });
  }

  /**
   * Check if an element is visible on screen
   * @param {string} description - Description of the element to look for
   * @param {boolean} wait - Whether to wait for the element to appear
   * @param {number} timeout - Maximum time to wait (in seconds)
   * @param {number} interval - Interval between checks (in seconds)
   * @returns {Promise<Object>} Result with element visibility info
   */
  async see(description, wait = true, timeout = 5.0, interval = 0.5) {
    return await callApi('post', '/cb/see', { 
      description, 
      wait, 
      timeout, 
      interval 
    });
  }

  /**
   * Take a screenshot
   * @returns {Promise<Object>} Result with screenshot as base64 string
   */
  async getScreenshot() {
    return await callApi('get', '/cb/screenshot');
  }

  /**
   * Navigate to a URL in a browser
   * @param {string} url - The URL to navigate to
   * @param {string} browser - Browser to use (default: 'Safari')
   * @returns {Promise<Object>} Result of the operation
   */
  async navigateUrl(url, browser = 'Safari') {
    return await callApi('post', '/cb/navigate-url', { url, browser });
  }

  /**
   * Upload a reference element image
   * This requires a more complex interaction with a file input
   * @param {File} file - The image file to upload
   * @returns {Promise<Object>} Result of the upload operation
   */
  async uploadReferenceElement(file) {
    console.log('Uploading reference element:', file.name);
    return await ipcRenderer.invoke('upload-reference-element-file', { 
      filename: file.name,
      fileData: await new Promise(resolve => {
        const reader = new FileReader();
        reader.onloadend = () => resolve(reader.result);
        reader.readAsDataURL(file);
      })
    });
  }

  /**
   * Run a sequence of automation steps
   * @param {Array<Object>} steps - Array of step objects with action, params, and delay
   * @returns {Promise<Array<Object>>} Results of each step
   * 
   * Each step should have:
   * - action: String name of the action (openApp, executeAction, etc.)
   * - params: Parameters for the action
   * - delay: Optional delay after this step (in ms)
   */
  async runSequence(steps) {
    const results = [];
    
    for (const step of steps) {
      try {
        let result;
        
        switch (step.action) {
          case 'openApp':
            result = await this.openApp(step.params.appName, step.params.waitTime);
            break;
          case 'executeAction':
            result = await this.executeAction(
              step.params.query,
              step.params.referenceElement,
              step.params.elementsConf,
              step.params.containerConf
            );
            break;
          case 'pressKey':
            result = await this.pressKey(step.params.key);
            break;
          case 'see':
            result = await this.see(
              step.params.description,
              step.params.wait,
              step.params.timeout,
              step.params.interval
            );
            break;
          case 'getScreenshot':
            result = await this.getScreenshot();
            break;
          case 'navigateUrl':
            result = await this.navigateUrl(step.params.url, step.params.browser);
            break;
          default:
            result = { success: false, error: `Unknown action: ${step.action}` };
        }
        
        results.push({ 
          step: step.action, 
          result,
          success: result.success || false
        });
        
        // If the step failed and we're not set to continue on error, stop the sequence
        if ((!result.success) && !step.continueOnError) {
          break;
        }
        
        // Wait for the specified delay if any
        if (step.delay) {
          await new Promise(resolve => setTimeout(resolve, step.delay));
        }
        
      } catch (error) {
        results.push({ 
          step: step.action, 
          result: { success: false, error: error.message },
          success: false
        });
        
        // If we're not set to continue on error, stop the sequence
        if (!step.continueOnError) {
          break;
        }
      }
    }
    
    return results;
  }

  /**
   * Get installed apps
   * @returns {Promise<Object>} List of installed apps
   */
  async getInstalledApps() {
    return await ipcRenderer.invoke('cb-get-installed-apps');
  }

  /**
   * Compare two images and get similarity metrics
   * @param {Object} options - Comparison options
   * @param {string} [options.image1] - First image as base64 string
   * @param {string} [options.image2] - Second image as base64 string
   * @param {string} [options.image1Id] - ID of first reference image
   * @param {string} [options.image2Id] - ID of second reference image
   * @param {boolean} [options.normalize=true] - Whether to normalize the images
   * @returns {Promise<Object>} Comparison results with similarity metrics
   */
  async compareImages({ image1, image2, image1Id, image2Id, normalize = true }) {
    return await ipcRenderer.invoke('cb-compare-images', {
      image1, 
      image2, 
      image1Id, 
      image2Id, 
      normalize
    });
  }

  /**
   * Perform a swipe action
   * @param {string} direction - Swipe direction ('left', 'right', 'up', 'down')
   * @returns {Promise<Object>} Result of the swipe action
   */
  async swipe(direction) {
    return await ipcRenderer.invoke('cb-swipe', { direction });
  }

  /**
   * Start the Tinder automation loop
   * @param {Object} config - Configuration options
   * @param {number} [config.similarityThreshold=0.7] - Threshold for image similarity
   * @param {number} [config.delayBetweenSwipes=2000] - Delay between swipes in ms
   * @param {number} [config.maxSwipes=100] - Maximum number of swipes
   * @returns {Promise<Object>} Result of starting the automation
   */
  async startTinderLoop(config = {}) {
    return await ipcRenderer.invoke('cb-start-tinder-loop', {
      similarity_threshold: config.similarityThreshold || 0.7,
      delay_between_swipes: config.delayBetweenSwipes / 1000 || 2.0,
      max_swipes: config.maxSwipes || 100
    });
  }

  /**
   * Pause the running Tinder automation
   * @returns {Promise<Object>} Result with current automation stats
   */
  async pauseTinderLoop() {
    return await ipcRenderer.invoke('cb-pause-tinder-loop');
  }

  /**
   * Resume a paused Tinder automation
   * @returns {Promise<Object>} Result with current automation stats
   */
  async resumeTinderLoop() {
    return await ipcRenderer.invoke('cb-resume-tinder-loop');
  }

  /**
   * Stop the Tinder automation
   * @returns {Promise<Object>} Result with final automation stats
   */
  async stopTinderLoop() {
    return await ipcRenderer.invoke('cb-stop-tinder-loop');
  }

  /**
   * Run sequence of steps for Tinder
   * @returns {Promise<Object>} Results of the Tinder sequence
   */
  async runTinderSequence() {
    const steps = [
      {
        action: 'openApp',
        params: {
          appName: 'iPhone Mirroring',
          waitTime: 5.0
        }
      },
      {
        action: 'executeAction',
        params: {
          query: 'Click on Search'
        },
        delay: 1000
      },
      // Type "Tinder" - one character at a time
      ...Array.from('Tinder').map(char => ({
        action: 'pressKey',
        params: { key: char },
        delay: 100
      })),
      {
        action: 'executeAction',
        params: {
          query: 'Click on the Tinder icon'
        },
        delay: 3000
      },
      {
        action: 'getScreenshot'
      }
    ];
    
    return await this.runSequence(steps);
  }

  /**
   * Get detailed Tinder automation statistics
   * @returns {Promise<Object>} Detailed statistics and metrics
   */
  async getTinderStats() {
    return await ipcRenderer.invoke('cb-get-tinder-stats');
  }

  /**
   * Clean up resources after automation
   * @returns {Promise<Object>} Result of the cleanup operation
   */
  async cleanupResources() {
    try {
      console.log('Cleaning up resources...');
      return await callApi('post', '/cb/cleanup-resources');
    } catch (error) {
      console.error('Failed to clean up resources:', error);
      return { success: false, error: error.message };
    }
  }
}

// Export the API
module.exports = new CoffeeBlackApi(); 