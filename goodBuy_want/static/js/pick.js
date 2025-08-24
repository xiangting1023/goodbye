// 卡片點選 切 radio  加上綠框＆「已選擇」提示
document.querySelectorAll('[data-card-radio]').forEach(function(radio){
    const card = radio.closest('.card');
    card.addEventListener('click', () => {
    document.querySelectorAll('[data-card-radio]').forEach(r => {
        r.checked = false;
        r.closest('.card').classList.remove('border-success');
    });
    radio.checked = true;
    card.classList.add('border-success');
    });
});

// 點卡片 勾選對應 radio 套上 selected 樣式
(function () {
    const labels = document.querySelectorAll('.card-selectable');
    labels.forEach(lb => {
    lb.addEventListener('click', () => {
        // 清掉其他 selected
        labels.forEach(x => x.classList.remove('selected'));
        // 勾選
        const radio = lb.querySelector('[data-shop-radio]');
        radio.checked = true;
        // 樣式
        lb.classList.add('selected');
    });
    });
})();