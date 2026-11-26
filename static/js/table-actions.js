document.addEventListener("DOMContentLoaded", () => {
    const pageSize = 8;

    document.querySelectorAll("[data-print]").forEach((button) => {
        button.addEventListener("click", () => window.print());
    });

    document.querySelectorAll("[data-table-search]").forEach((input) => {
        const tableBody = document.getElementById(input.dataset.tableSearch);
        if (!tableBody) {
            return;
        }

        const rows = Array.from(tableBody.querySelectorAll("tr:not([data-table-empty])"));
        const emptyRow = tableBody.querySelector("[data-table-empty]");
        const filterButtons = Array.from(document.querySelectorAll("[data-table-filter-target]"))
            .filter((button) => button.dataset.tableFilterTarget === tableBody.id);
        const paginationControls = Array.from(document.querySelectorAll("[data-table-pagination-target]"))
            .filter((control) => control.dataset.tablePaginationTarget === tableBody.id);
        let selectedCategory = "todos";
        let currentPage = 1;

        const renderTable = () => {
            const query = input.value.trim().toLocaleLowerCase();
            const filteredRows = rows.filter((row) => {
                const matchesQuery = row.textContent.toLocaleLowerCase().includes(query);
                const matchesCategory = selectedCategory === "todos"
                    || row.dataset.category === selectedCategory;
                return matchesQuery && matchesCategory;
            });
            const pageCount = Math.max(1, Math.ceil(filteredRows.length / pageSize));
            currentPage = Math.min(currentPage, pageCount);

            const firstRow = (currentPage - 1) * pageSize;
            rows.forEach((row) => {
                row.hidden = true;
            });
            filteredRows.slice(firstRow, firstRow + pageSize).forEach((row) => {
                row.hidden = false;
            });
            if (emptyRow) {
                emptyRow.hidden = filteredRows.length !== 0;
            }

            paginationControls.forEach((control) => {
                if (control.dataset.tablePagination === "current") {
                    control.textContent = `${currentPage} / ${pageCount}`;
                } else if (control.dataset.tablePagination === "prev") {
                    control.disabled = currentPage === 1;
                } else if (control.dataset.tablePagination === "next") {
                    control.disabled = currentPage === pageCount;
                }
            });
        };

        input.addEventListener("input", () => {
            currentPage = 1;
            renderTable();
        });

        filterButtons.forEach((button) => {
            button.addEventListener("click", () => {
                selectedCategory = button.dataset.tableFilter;
                currentPage = 1;
                filterButtons.forEach((filterButton) => {
                    const isSelected = filterButton === button;
                    filterButton.classList.toggle("active", isSelected);
                    filterButton.setAttribute("aria-pressed", String(isSelected));
                });
                renderTable();
            });
        });

        paginationControls.forEach((control) => {
            control.addEventListener("click", () => {
                if (control.dataset.tablePagination === "prev") {
                    currentPage -= 1;
                } else if (control.dataset.tablePagination === "next") {
                    currentPage += 1;
                }
                renderTable();
            });
        });

        renderTable();
    });

    document.querySelectorAll("form[data-confirm]").forEach((form) => {
        form.addEventListener("submit", (event) => {
            if (!window.confirm(form.dataset.confirm)) {
                event.preventDefault();
            }
        });
    });
});
