document.addEventListener("DOMContentLoaded", () => {
    document.querySelectorAll("[data-print]").forEach((button) => {
        button.addEventListener("click", () => window.print());
    });

    document.querySelectorAll("[data-table-search]").forEach((input) => {
        const tableBody = document.getElementById(input.dataset.tableSearch);
        if (!tableBody) {
            return;
        }
        input.addEventListener("input", () => {
            const query = input.value.trim().toLocaleLowerCase();
            tableBody.querySelectorAll("tr").forEach((row) => {
                row.hidden = !row.textContent.toLocaleLowerCase().includes(query);
            });
        });
    });

    document.querySelectorAll("form[data-confirm]").forEach((form) => {
        form.addEventListener("submit", (event) => {
            if (!window.confirm(form.dataset.confirm)) {
                event.preventDefault();
            }
        });
    });
});
