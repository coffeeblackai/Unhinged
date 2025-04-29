# Unhinged

An Electron application that automates Tinder swiping based on image similarity matching. This app uses a Python backend with the coffeeblack library to control the iPhone through the Mirror app.

## Features

- Upload reference images of people you find attractive
- Automatic profile matching using image similarity algorithms
- Configure similarity threshold, delay between swipes, and maximum swipes
- Real-time logging of the automation process

## Prerequisites

- Node.js (v14+)
- Python (v3.7+)
- iPhone with the Mirror app installed
- Tinder app installed on your iPhone

## Installation

1. Clone this repository:
   ```
   git clone <repository-url>
   cd type-swiper
   ```

2. Install Node.js dependencies:
   ```
   npm install
   ```

3. Install Python dependencies:
   ```
   pip install -r src/python/requirements.txt
   ```

   Note: The coffeeblack package is required for iPhone automation. Make sure it's properly installed.

## Usage

1. Start the application:
   ```
   npm start
   ```

2. Upload reference images:
   - Click on the "Click or drag images here to upload" area
   - Select one or more images of people you find attractive

3. Configure automation settings:
   - Set the similarity threshold (how closely a profile must match your reference images)
   - Set the delay between swipes (in milliseconds)
   - Set the maximum number of profiles to swipe on

4. Connect your iPhone with the Mirror app:
   - Open the Mirror app on your iPhone
   - Make sure your iPhone and computer are on the same network

5. Start the automation:
   - Click the "Start Automation" button
   - The app will open Tinder and begin swiping based on your preferences

6. Monitor the process:
   - The log section will show real-time updates
   - You can stop the automation at any time by clicking "Stop Automation"

## How It Works

1. The Electron app sends commands to a local Python server
2. The Python server uses coffeeblack to control the iPhone through the Mirror app
3. The app takes screenshots of Tinder profiles and compares them with your reference images
4. Based on the similarity score, the app decides to swipe right (like) or left (pass)

## Notes

- The app requires the coffeeblack library, which is used to interact with the iPhone
- For best results, use clear, front-facing photos as reference images
- Adjust the similarity threshold based on your preferences (higher values require closer matches)
- This app is for educational purposes only

## License

MIT 