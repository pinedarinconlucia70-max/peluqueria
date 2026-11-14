document.addEventListener("DOMContentLoaded", () => {
    document.querySelectorAll("[data-menu-toggle]").forEach((toggle) => {
        const changeMenu = () => {
            document.getElementById("sidebar")?.classList.toggle("active");
        };
        toggle.addEventListener("click", changeMenu);
        toggle.addEventListener("keydown", (event) => {
            if (event.key === "Enter" || event.key === " ") {
                event.preventDefault();
                changeMenu();
            }
        });
    });

    document.querySelector("[data-back]")?.addEventListener("click", () => {
        window.location.assign("/");
    });

    const login = document.getElementById("container-login");
    const registration = document.getElementById("container-registro");
    document.querySelector("[data-show-register]")?.addEventListener("click", (event) => {
        event.preventDefault();
        if (login && registration) {
            login.hidden = true;
            registration.hidden = false;
        }
    });
    document.querySelector("[data-show-login]")?.addEventListener("click", (event) => {
        event.preventDefault();
        if (login && registration) {
            login.hidden = false;
            registration.hidden = true;
        }
    });

    const iframe = document.getElementById("frame");
    document.querySelectorAll("[data-dashboard-url]").forEach((button) => {
        button.addEventListener("click", () => {
            if (iframe) {
                iframe.src = button.dataset.dashboardUrl;
            }
            document.querySelectorAll(".menu button").forEach((item) => {
                item.classList.toggle("active", item === button);
            });
        });
    });

    const days = ["domingo", "lunes", "martes", "miercoles", "jueves", "viernes", "sabado"];
    document.getElementById(days[new Date().getDay()])?.classList.add("active");

    document.querySelectorAll(".solo-numeros").forEach((input) => {
        input.addEventListener("input", () => {
            input.value = input.value.replace(/\D/g, "");
        });
    });

    document.querySelectorAll("[data-service-price]").forEach((select) => {
        select.addEventListener("change", () => {
            const priceInput = document.getElementById(select.dataset.servicePrice);
            const selectedOption = select.selectedOptions[0];
            if (priceInput && selectedOption?.dataset.price) {
                priceInput.value = selectedOption.dataset.price;
            }
        });
    });
});
