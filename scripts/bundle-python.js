const { spawn } = require('child_process');
const fs = require('fs');
const path = require('path');

// Paths
const rootDir = path.resolve(__dirname, '..');
const pythonDir = path.join(rootDir, 'src', 'python');
const requirementsPath = path.join(pythonDir, 'requirements.txt');
const targetDir = path.join(rootDir, 'python_packages');

console.log('=== Bundling Python Packages ===');
console.log(`Requirements file: ${requirementsPath}`);
console.log(`Target directory: ${targetDir}`);

// Ensure the target directory exists
if (!fs.existsSync(targetDir)) {
  console.log('Creating target directory...');
  fs.mkdirSync(targetDir, { recursive: true });
}

// Function to run a command
function runCommand(command, args) {
  return new Promise((resolve, reject) => {
    console.log(`Running: ${command} ${args.join(' ')}`);
    
    const proc = spawn(command, args, {
      stdio: 'inherit',
      shell: process.platform === 'win32' // Use shell on Windows
    });
    
    proc.on('close', code => {
      if (code === 0) {
        resolve();
      } else {
        reject(new Error(`Command failed with exit code ${code}`));
      }
    });
    
    proc.on('error', err => {
      reject(err);
    });
  });
}

// Determine which Python command to use
async function getPythonCommand() {
  try {
    await runCommand('python3', ['--version']);
    return 'python3';
  } catch (err) {
    try {
      await runCommand('python', ['--version']);
      return 'python';
    } catch (err) {
      throw new Error('Neither python3 nor python was found. Please install Python.');
    }
  }
}

async function main() {
  try {
    // Check if requirements.txt exists
    if (!fs.existsSync(requirementsPath)) {
      throw new Error(`requirements.txt not found at ${requirementsPath}`);
    }

    // Get Python command
    const pythonCmd = await getPythonCommand();
    console.log(`Using Python command: ${pythonCmd}`);
    
    // Install packages to the target directory
    console.log('Installing Python packages...');
    await runCommand(pythonCmd, [
      '-m', 'pip', 'install',
      '-r', requirementsPath,
      '--target', targetDir,
      '--upgrade'
    ]);
    
    console.log('Successfully bundled Python packages!');
  } catch (err) {
    console.error('Error bundling Python packages:', err.message);
    process.exit(1);
  }
}

main(); 