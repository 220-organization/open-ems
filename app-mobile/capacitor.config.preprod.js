/** @type {import('@capacitor/cli').CapacitorConfig} */
const config = {
  appId: 'com.km220.openems.preprod',
  appName: 'Open EMS (preprod)',
  webDir: 'www',
  server: {
    url: 'https://220-km-preprod.com:9220',
    androidScheme: 'https',
    cleartext: false,
    allowNavigation: ['220-km.com', '220-km-preprod.com'],
  },
  ios: {
    contentInset: 'automatic',
    allowsLinkPreview: false,
    scrollEnabled: true,
  },
};

module.exports = config;
