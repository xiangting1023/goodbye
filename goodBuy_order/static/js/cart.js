// // cart.js

// document.addEventListener("DOMContentLoaded", function () {
//   // 更新單一 group 的總價
//   function updateGroupTotal(groupElement) {
//     const items = groupElement.querySelectorAll(".cart-item");
//     let total = 0;

//     items.forEach((item) => {
//       const checkbox = item.querySelector(".item-checkbox");
//       const quantityInput = item.querySelector(".quantity-input");
//       const price = parseFloat(item.querySelector(".text-danger").textContent);

//       if (checkbox.checked) {
//         const quantity = parseInt(quantityInput.value);
//         total += price * quantity;
//       }
//     });

//     groupElement.querySelector(".group-total").textContent = `${total}$`;
//   }

//   // 處理每個 group checkbox（全選）
//   document.querySelectorAll(".group-checkbox").forEach((groupCheckbox, index) => {
//     groupCheckbox.addEventListener("change", function () {
//       const groupElement = groupCheckbox.closest(".cart-group");
//       const itemCheckboxes = groupElement.querySelectorAll(".item-checkbox");
//       itemCheckboxes.forEach((cb) => (cb.checked = groupCheckbox.checked));
//       updateGroupTotal(groupElement);
//     });
//   });

//   // 個別 checkbox 切換時也更新小計
//   document.querySelectorAll(".item-checkbox").forEach((checkbox) => {
//     checkbox.addEventListener("change", function () {
//       const groupElement = checkbox.closest(".cart-group");
//       updateGroupTotal(groupElement);
//     });
//   });

//   // 數量變更時觸發重新計算
//   document.querySelectorAll(".quantity-input").forEach((input) => {
//     input.addEventListener("change", function () {
//       const groupElement = input.closest(".cart-group");
//       updateGroupTotal(groupElement);
//     });
//   });
// });

document.addEventListener("DOMContentLoaded", function () {
  // 更新單一 group 的總價
  function updateGroupTotal(groupElement) {
    const items = groupElement.querySelectorAll(".cart-item");
    let total = 0;

    items.forEach((item) => {
      const checkbox = item.querySelector(".item-checkbox");
      const quantityInput = item.querySelector(".quantity-input");
      const price = parseFloat(item.querySelector(".text-danger").textContent);

      if (checkbox.checked) {
        const quantity = parseInt(quantityInput.value);
        total += price * quantity;
      }
    });

    groupElement.querySelector(".group-total").textContent = `${total}$`;
  }

  // 每團 checkbox 勾選時，同步每個 item checkbox 並更新總計
  document.querySelectorAll(".group-checkbox").forEach((groupCheckbox) => {
    groupCheckbox.addEventListener("change", function () {
      const groupElement = groupCheckbox.closest(".cart-group");
      const itemCheckboxes = groupElement.querySelectorAll(".item-checkbox");
      itemCheckboxes.forEach((cb) => (cb.checked = groupCheckbox.checked));
      updateGroupTotal(groupElement);
      updateCartCount()
    });
  });

  // 單一商品 checkbox 勾選時：
  // 1. 更新總計
  // 2. 若全部 item 都勾選，group checkbox 也勾選
  document.querySelectorAll(".item-checkbox").forEach((checkbox) => {
    checkbox.addEventListener("change", function () {
      const groupElement = checkbox.closest(".cart-group");
      const allItems = groupElement.querySelectorAll(".item-checkbox");
      const allChecked = [...allItems].every(cb => cb.checked);
      groupElement.querySelector(".group-checkbox").checked = allChecked;
      updateGroupTotal(groupElement); //更新總計
      updateCartCount(); // 更新購物車商品數量顯示
    });
  });

  // 數量變更時自動更新金額
  document.querySelectorAll(".quantity-input").forEach((input) => {
    input.addEventListener("change", function () {
      const groupElement = input.closest(".cart-group");
      updateGroupTotal(groupElement); //更新總計
      updateCartCount(); // 更新購物車商品數量顯示
    });
  });

  // 表單送出前只保留被勾選的 cart_ids
  const cartForm = document.getElementById("cart-form");
  if (cartForm) {
    cartForm.addEventListener("submit", function (e) {
      const allCheckboxes = cartForm.querySelectorAll(".item-checkbox");
      allCheckboxes.forEach((cb) => {
        if (!cb.checked) {
          cb.disabled = true; // 取消未勾選的，不送出
        }
      });
    });
  }

  // 更新購物車商品數量顯示
  function updateCartCount() {
  const checkedItems = document.querySelectorAll(".item-checkbox:checked");
  const count = checkedItems.length;
  document.getElementById("cart-count").textContent = `已選取 ${count} 個商品`;
  updateCartCount() // 初始化時更新一次
  }

  document.addEventListener("DOMContentLoaded", function () {
  const checkoutForm = document.getElementById("checkout-form");
  const checkoutButton = document.getElementById("checkout-button");

  if (checkoutForm && checkoutButton) {
    checkoutButton.addEventListener("click", function () {
      // 清空表單內容，只保留 CSRF
      checkoutForm.innerHTML = `{% csrf_token %}`;

      const checkedBoxes = document.querySelectorAll(".item-checkbox:checked");
      if (checkedBoxes.length === 0) {
        alert("請先勾選要結帳的商品！");
        return;
      }

      checkedBoxes.forEach((box) => {
        const input = document.createElement("input");
        input.type = "hidden";
        input.name = "cart_ids";
        input.value = box.value;
        checkoutForm.appendChild(input);
      });

      checkoutForm.submit();
      });
    }
  });

});

