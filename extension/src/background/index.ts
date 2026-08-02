
// Opens the side panel when the extension icon is clicked
console.log('background loaded')
chrome.sidePanel
  .setPanelBehavior({ openPanelOnActionClick: true })
  .then(() => console.log('panel behavior set'))
  .catch((error) => console.error('sidePanel error:', error))

// Opens the side panel when the hotkey command is triggered
chrome.commands.onCommand.addListener((command) => {
  if (command === 'open_side_panel') {
    chrome.windows.getCurrent((w) => {
      chrome.sidePanel.open({ windowId: w.id! })
        .then(() => console.log('Side panel opened by hotkey command!'))
        .catch((error) => console.error('sidePanel open error:', error))
    })
  }
  
  console.log(`Command "${command}" triggered`);
})