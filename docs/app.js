const header = document.querySelector(".site-header");

function updateHeaderShadow() {
  header.toggleAttribute("data-scrolled", window.scrollY > 8);
}

window.addEventListener("scroll", updateHeaderShadow, { passive: true });
updateHeaderShadow();
