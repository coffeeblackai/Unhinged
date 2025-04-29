// This is a simplified notarization script.
// For production, you would want to set up proper Apple Developer credentials.
const { notarize } = require('@electron/notarize');
require('dotenv').config();

exports.default = async function notarizing(context) {
  const { electronPlatformName, appOutDir } = context;  
  if (electronPlatformName !== 'darwin') {
    return;
  }

  console.log('Notarizing app...');
  
  const appName = context.packager.appInfo.productFilename;
  const appPath = `${appOutDir}/${appName}.app`;
  
  // These would normally come from environment variables or a secure source
  const appleId = process.env.APPLE_ID;
  const appleIdPassword = process.env.APPLE_ID_PASSWORD;
  const teamId = process.env.APPLE_TEAM_ID;
  
  if (!appleId || !appleIdPassword || !teamId) {
    console.warn('Skipping notarization due to missing credentials. Set APPLE_ID, APPLE_ID_PASSWORD, and APPLE_TEAM_ID environment variables.');
    return;
  }

  try {
    await notarize({
      appPath,
      appBundleId: 'com.electron.unhinged',
      appleId,
      appleIdPassword,
      teamId
    });
    console.log(`Successfully notarized ${appName}`);
  } catch (error) {
    console.error('Notarization failed:', error);
  }
}; 