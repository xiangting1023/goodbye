document.addEventListener('DOMContentLoaded', () => {
    const tabs = ['order', 'payment', 'shipping'];
    const buttons = document.querySelectorAll('.action-btn');

    function showTab(tabName) {
        tabs.forEach(name => {
            const el = document.getElementById('tab-' + name);
            if (el) el.style.display = (name === tabName) ? 'block' : 'none';
        });
    }

    buttons.forEach(btn => {
        btn.addEventListener('click', () => {
            // 移除所有按鈕的 active
            buttons.forEach(b => b.classList.remove('active'));
            // 當前按鈕加 active
            btn.classList.add('active');

            // 顯示對應 tab
            const tabName = btn.getAttribute('data-tab');
            showTab(tabName);
        });
    });

    // 預設顯示第一個 tab
    if(buttons[0]) {
        buttons[0].classList.add('active');
        showTab(buttons[0].getAttribute('data-tab'));
    }
});
