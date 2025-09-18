/* ==========================
   create_comment.js
   星星評分功能 (點選 + 懸停 + 填滿效果)
========================== */

document.addEventListener("DOMContentLoaded", () => {
    const stars = document.querySelectorAll("#star-rating .star"); // 星星元素集合
    const rankInput = document.getElementById("id_rank");           // 隱藏 input，提交分數
    let currentRating = parseInt(rankInput.value) || 0;             // 當前分數

    // --------------------------
    // 函數：更新星星顯示 (實心/空心)
    // --------------------------
    function updateStars(value) {
        stars.forEach((star, index) => {
            if (index < value) {
                star.classList.remove("fa-regular");
                star.classList.add("fa-solid", "filled"); // 實心黃星
            } else {
                star.classList.remove("fa-solid", "filled");
                star.classList.add("fa-regular");        // 空心灰星
            }
        });
    }

    // 初始化星星顯示
    updateStars(currentRating);

    // --------------------------
    // 事件：滑鼠懸停 (hover)
    // --------------------------
    stars.forEach((star, index) => {
        const value = parseInt(star.dataset.value);

        // 滑鼠移入
        star.addEventListener("mouseover", () => {
            updateStars(value); // 顯示暫時填滿到滑鼠位置
        });

        // 滑鼠移出
        star.addEventListener("mouseout", () => {
            updateStars(currentRating); // 回復到當前選擇的星數
        });

        // 點選星星
        star.addEventListener("click", () => {
            currentRating = value;
            rankInput.value = value;   // 更新隱藏 input
            updateStars(currentRating); 
        });
    });
});
