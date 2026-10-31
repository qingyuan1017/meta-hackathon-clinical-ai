# Clinical AI Agent mobile app

Native iOS and Android companion app for the Clinical AI Artifact Workbench. It reads job history and sanitized agent traces from the existing FastAPI backend and sends revision guidance at human-review gates.

## Run locally

1. Install dependencies:

   ```powershell
   cd mobile
   npm install
   ```

2. For the Android emulator, start the emulator first and run `npm run android`; the command creates an ADB reverse tunnel to the backend automatically. A physical phone needs the development computer's LAN IP, such as `http://192.168.1.20:8000`, configured in `.env` or the app's Settings screen.

3. Start the backend from the repository root, then start Expo:

   ```powershell
   npm start
   ```

4. Open the project in Expo Go, an Android emulator, or the iOS simulator. The backend address can also be changed and tested from the app's Settings tab.

The development configuration permits local HTTP traffic so a phone can reach the LAN-hosted backend. Use HTTPS and remove the cleartext allowances in `app.json` before a public production release.

## Native builds

The app includes `eas.json` profiles for development, internal preview, and production builds. After authenticating with Expo:

```powershell
npx eas-cli build --platform android --profile preview
npx eas-cli build --platform ios --profile preview
```

iOS device/App Store builds require an Apple Developer account. Android store distribution requires a Google Play developer account.

## Safety

This is a hackathon demonstration. Do not use PHI or identifiable patient data. Agent output is not validated for clinical or regulatory use and requires qualified review.
