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
      updateCartCount(); // 更新數量
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
// 先做前端上限檢查，再送到後端保存
// 工具：抓 CSRF
function getCsrf() {
  const el = document.querySelector('input[name="csrfmiddlewaretoken"]');
  return el ? el.value : '';
}

// 綁定所有數量欄
const qtyInputs = document.querySelectorAll(".quantity-input");
console.log("[cart] quantity inputs =", qtyInputs.length);

qtyInputs.forEach((input) => {
  // 讓使用者按上下鍵就即時更新小計
  input.addEventListener("input", function () {
    const group = input.closest(".cart-group");
    // 本地 min/max 防呆
    const max = parseInt(input.getAttribute("max") || "9999", 10);
    const min = parseInt(input.getAttribute("min") || "1", 10);
    let v = parseInt(input.value || "0", 10);
    if (isNaN(v) || v < min) v = min;
    if (v > max) {
      input.value = String(max);
      alert(`這項商品已沒有更多數量可買，最多 ${max} 件。`);
    }
    updateGroupTotal(group);
    updateCartCount();
  });

  input.addEventListener("change", async function () {
    const url = input.dataset.updateUrl;
    const csrf = getCsrf();
    const group = input.closest(".cart-group");
    const qty = parseInt(input.value || "0", 10);

    console.log("[cart] change qty ->", { qty, url, hasCsrf: !!csrf });

    if (!url) {
      console.warn("[cart] 找不到 data-update-url，請確認 cart.html 是否有加上。");
      return;
    }
    if (!csrf) {
      console.warn("[cart] 找不到 CSRF token，請確認頁面內有 {% csrf_token %}。");
      return;
    }

    try {
      const res = await fetch(url, {
        method: "POST",
        headers: {
          "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
          "X-CSRFToken": csrf,
        },
        body: new URLSearchParams({ quantity: String(qty) }).toString(),
        redirect: "follow",
      });

      // 正常 Django 會 302 -> 200 刷 messages 顯示出來
      if (res.ok) {
        // 後端可能把超過庫存的數量壓回上限；重整後就能看到提示訊息
        location.reload();
      } else {
        console.error("[cart] 後端回應非 2xx：", res.status);
        alert("更新數量失敗，請稍後再試");
      }
    } catch (err) {
      console.error("[cart] fetch error", err);
      alert("更新數量時發生錯誤，請稍後再試。");
    }
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
  }

  updateCartCount(); // 初始化時更新一次

  // 結帳按鈕邏輯：收集勾選項目並送出 checkout-form
  const checkoutForm = document.getElementById("checkout-form");
  const checkoutButton = document.getElementById("checkout-button");

  if (checkoutForm && checkoutButton) {
    checkoutButton.addEventListener("click", function () {
      const checkedBoxes = document.querySelectorAll(".item-checkbox:checked");
      if (checkedBoxes.length === 0) {
        alert("請先勾選要結帳的商品！");
        return;
      }

      // 清空 checkoutForm，只保留 CSRF token
      const csrfInput = checkoutForm.querySelector('input[name="csrfmiddlewaretoken"]');
      const csrfClone = csrfInput ? csrfInput.cloneNode() : null;

      checkoutForm.innerHTML = ''; // 清空
      if (csrfClone) {
        checkoutForm.appendChild(csrfClone); // 加回複製的 token
      }

      // 加入勾選的 cart_ids
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
  const cbs = document.querySelectorAll('.item-checkbox:checked');
  const kinds = new Set([...cbs].map(cb => cb.dataset.type)); // e.g. {'normal', 'rush'}
  if (kinds.size > 1) {
    alert('一般商店與多帶商店不可一起結帳，請分開勾選。');
    // 也可以自動取消剛剛那個勾選
  }
});

