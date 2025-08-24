function showTab(tabName) {
    const sellerContent = document.getElementById("seller-content");
    sellerContent.innerHTML = document.getElementById("tab-" + tabName).innerHTML;
}


document.querySelectorAll('.action-btn').forEach(button => {
  button.addEventListener('click', () => {
    // 移除其他按鈕 active
    document.querySelectorAll('.action-btn').forEach(btn => btn.classList.remove('active'));
    // 自己加 active
    button.classList.add('active');

    // 切換內容（假設有showTab函式）
    showTab(button.getAttribute('onclick').match(/'(\w+)'/)[1]);
  });
});

// 頁面載入時，預設第一個按鈕 active
window.onload = () => {
  const firstBtn = document.querySelector('.action-btn');
  if(firstBtn) {
    firstBtn.classList.add('active');
  }
};

