// 判斷目前順序
document.addEventListener("DOMContentLoaded", () => {
  const currentStep = document.body.getAttribute("data-checkout-step");
  if (!currentStep) return;

  const steps = document.querySelectorAll(".checkout-steps .step");
  steps.forEach((step) => {
    const index = step.getAttribute("data-step-index");
    if (index === currentStep) {
      step.classList.add("active");
    }
  });
});