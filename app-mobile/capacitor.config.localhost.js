/** @type {import('@capacitor/cli').CapacitorConfig} */
const config = {
  appId: 'com.km220.openems.localhost',
  appName: 'Open EMS (localhost)',
  webDir: 'www',
  server: {
    url: 'http://localhost:9220',
    androidScheme: 'http',
    cleartext: true,
    allowNavigation: ['localhost', '127.0.0.1'],
  },
  ios: {
    contentInset: 'automatic',
    allowsLinkPreview: false,
    scrollEnabled: true,
  },
};

module.exports = config;
