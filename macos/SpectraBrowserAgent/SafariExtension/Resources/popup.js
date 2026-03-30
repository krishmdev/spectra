document.addEventListener('DOMContentLoaded', () => {
    const input = document.getElementById('task-input');
    const button = document.getElementById('send-button');
    const titleView = document.getElementById('page-title');

    // Get current tab title
    browser.tabs.query({ active: true, currentWindow: true }).then((tabs) => {
        if (tabs[0]) {
            titleView.textContent = tabs[0].title;
        }
    });

    button.addEventListener('click', () => {
        const query = input.value.trim();
        if (query) {
            browser.runtime.sendNativeMessage("com.spectra.browser.agent", { task: query }).then((response) => {
                window.close();
            }).catch((error) => {
                console.error("Native message error: ", error);
            });
        }
    });

    input.addEventListener('keypress', (e) => {
        if (e.key === 'Enter') {
            button.click();
        }
    });
});
