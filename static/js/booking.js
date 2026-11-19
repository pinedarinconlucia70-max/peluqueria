document.addEventListener("DOMContentLoaded", () => {
    const form = document.querySelector("[data-booking-form]");
    if (!form) {
        return;
    }

    const dateInput = form.querySelector('input[name="fecha"]');
    const timeInput = form.querySelector('input[name="hora"]');

    const updateTimeMinimum = () => {
        if (!dateInput || !timeInput) {
            return;
        }
        if (dateInput.value !== dateInput.min) {
            timeInput.min = "08:00";
            return;
        }
        const now = new Date();
        const currentMinutes = now.getHours() * 60 + now.getMinutes();
        const nextSlot = Math.floor(currentMinutes / 30) * 30 + 30;
        const minimumMinutes = Math.max(8 * 60, nextSlot);
        timeInput.min = `${String(Math.floor(minimumMinutes / 60)).padStart(2, "0")}:${String(minimumMinutes % 60).padStart(2, "0")}`;
    };

    dateInput?.addEventListener("change", updateTimeMinimum);
    updateTimeMinimum();

    form.addEventListener("submit", (event) => {
        if (!form.reportValidity()) {
            event.preventDefault();
        }
    });
});
