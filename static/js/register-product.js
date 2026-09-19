(function () {
    const form = document.querySelector("form[data-register-product]");
    if (!form) return;
    const radios = form.querySelectorAll('input[name="product"]');
    const panels = form.querySelectorAll("[data-product-panel]");
    if (!radios.length || !panels.length) return;

    function selected() {
        const checked = form.querySelector('input[name="product"]:checked');
        return checked ? checked.value : "";
    }

    function sync() {
        const product = selected();
        panels.forEach(function (panel) {
            const match = panel.getAttribute("data-product-panel") === product;
            panel.hidden = !match;
            panel.querySelectorAll("input, textarea").forEach(function (field) {
                if (field.hasAttribute("data-keep-enabled")) return;
                field.disabled = !match;
            });
        });
    }

    radios.forEach(function (radio) {
        radio.addEventListener("change", sync);
    });
    sync();
})();
