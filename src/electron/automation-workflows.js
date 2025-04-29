/**
 * Automation Workflows
 * 
 * This module contains pre-defined automation workflows using the CoffeeBlack API.
 */

const coffeeBlackApi = require('./coffeeblack-api');

/**
 * Automation workflows for various tasks
 */
const AutomationWorkflows = {
  /**
   * Plural dashboard navigation workflow
   * 
   * This workflow:
   * 1. Opens Safari browser
   * 2. Navigates to the Plural dashboard
   * 3. Clicks on the 'Go to Console' button
   * 4. Uses a reference image to identify and click on the Pods button
   * 
   * @param {Object} options - Optional parameters
   * @returns {Promise<Object>} Results of the automation
   */
  async pluralDashboardNavigation(options = {}) {
    const browser = options.browser || 'Safari';
    const url = options.url || 'https://app.plural.sh/overview/clusters/self-hosted';
    const waitForLoadTime = options.waitForLoadTime || 5000;
    
    const steps = [
      {
        action: 'navigateUrl',
        params: {
          url,
          browser
        },
        delay: waitForLoadTime
      },
      {
        action: 'see',
        params: {
          description: 'Plural dashboard with possibly a "Go to Console" button',
          wait: true,
          timeout: 10.0
        }
      },
      {
        action: 'executeAction',
        params: {
          query: 'Click on the "Go to Console" button'
        },
        delay: 6000
      },
      {
        action: 'executeAction',
        params: {
          query: 'Click on the pods button',
          referenceElement: 'pods-button.png',
          elementsConf: 0.6,
          containerConf: 0.6
        },
        delay: 3000
      },
      {
        action: 'getScreenshot'
      }
    ];
    
    return await coffeeBlackApi.runSequence(steps);
  },
  
  /**
   * Tinder profile workflow with custom image matching
   * 
   * This workflow opens the Tinder app through iPhone Mirror
   * and manually navigates to a profile for matching.
   * 
   * @param {Object} options - Optional parameters including similarity_mode
   * @returns {Promise<Object>} Results of the automation
   */
  async tinderProfileCheck(options = {}) {
    const similarityMode = options.similarityMode || 'similar';
    
    const steps = [
      {
        action: 'openApp',
        params: {
          appName: 'iPhone Mirroring',
          waitTime: 5.0
        }
      },
      {
        action: 'getScreenshot'
      }
    ];
    
    const results = await coffeeBlackApi.runSequence(steps);
    
    // If we have a successful screenshot, we can analyze it
    const lastStep = results[results.length - 1];
    if (lastStep.success && lastStep.result.screenshot) {
      // Send the screenshot for comparison with reference images
      const screenshot = lastStep.result.screenshot;
      
      // This would be handled by the main Tinder comparison logic
      // Just providing the workflow connection point here
      console.log(`Screenshot captured for profile comparison (${similarityMode} mode)`);
    }
    
    return results;
  },
  
  /**
   * Browser automation workflow
   * 
   * A general-purpose browser automation workflow template
   * that can be customized with different steps.
   * 
   * @param {string} url - URL to navigate to
   * @param {Array<Object>} customSteps - Custom steps to execute after navigation
   * @param {Object} options - Additional options
   * @returns {Promise<Object>} Results of the automation
   */
  async browserAutomation(url, customSteps = [], options = {}) {
    const browser = options.browser || 'Safari';
    const waitForLoadTime = options.waitForLoadTime || 3000;
    
    // Initial steps to open browser and navigate to URL
    const initialSteps = [
      {
        action: 'navigateUrl',
        params: {
          url,
          browser
        },
        delay: waitForLoadTime
      }
    ];
    
    // Final step to take a screenshot
    const finalSteps = [
      {
        action: 'getScreenshot'
      }
    ];
    
    // Combine all steps
    const steps = [...initialSteps, ...customSteps, ...finalSteps];
    
    return await coffeeBlackApi.runSequence(steps);
  }
};

module.exports = AutomationWorkflows; 