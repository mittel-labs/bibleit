const header = document.querySelector(".site-header");

function updateHeaderShadow() {
  header.toggleAttribute("data-scrolled", window.scrollY > 8);
}

window.addEventListener("scroll", updateHeaderShadow, { passive: true });
updateHeaderShadow();


for (const button of document.querySelectorAll(".copy-command")) {
  button.addEventListener("click", async () => {
    const code = button.parentElement?.querySelector("code")?.innerText.trim();
    if (!code) {
      return;
    }

    await navigator.clipboard.writeText(code);
    button.textContent = "Copied";
    button.toggleAttribute("data-copied", true);

    window.setTimeout(() => {
      button.textContent = "Copy";
      button.removeAttribute("data-copied");
    }, 1600);
  });
}
