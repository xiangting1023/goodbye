function showTab(tabName) {
    const buyerContent = document.getElementById("buyer-content");
    buyerContent.innerHTML = document.getElementById("tabs-" + tabName).innerHTML;
}

// 按鈕切換 active
document.querySelectorAll('.action-btn').forEach(button => {
  button.addEventListener('click', () => {
    document.querySelectorAll('.action-btn').forEach(btn => btn.classList.remove('active'));
    button.classList.add('active');

    // 切換內容
    const tabName = button.getAttribute('onclick').match(/'(\w+)'/)[1];
    showTab(tabName);
  });
});

// 頁面載入時，預設第一個按鈕 active
window.onload = () => {
  const firstBtn = document.querySelector('.action-btn');
  if(firstBtn) {
    firstBtn.classList.add('active');
  }
};
