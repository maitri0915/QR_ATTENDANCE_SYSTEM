
"use strict";

document.addEventListener("DOMContentLoaded", () => {
    initializeTimetableFields();
    initializeDepartmentSemesterFilters();
});

/**
 * Switch between academic fields and event fields
 * depending on the selected timetable entry type.
 */
function initializeTimetableFields() {
    const entryType = document.querySelector("[data-timetable-type]");
    const academicFields = document.querySelector("[data-academic-fields]");
    const otherFields = document.querySelector("[data-other-fields]");

    if (!entryType || !academicFields || !otherFields) return;

    const facultySelect = document.getElementById("timetableFaculty");
    const subjectSelect = document.getElementById("timetableSubject");
    const divisionSelect = document.getElementById("timetableDivision");
    const titleInput = document.getElementById("timetableTitle");

    function updateTimetableFields() {
        const type = entryType.value;
        const isAcademic = type === "LECTURE" || type === "LAB";
        const isOther = type === "HOD_USE" || type === "OTHER";

        academicFields.hidden = !isAcademic;
        otherFields.hidden = !isOther;

        // Only academic entries require faculty, subject and division.
        if (facultySelect) facultySelect.required = isAcademic;
        if (subjectSelect) subjectSelect.required = isAcademic;
        if (divisionSelect) divisionSelect.required = isAcademic;

        // Other activities require a title.
        if (titleInput) titleInput.required = isOther;

        // Clear fields that do not apply to the selected entry type.
        if (!isAcademic) {
            if (facultySelect) facultySelect.value = "";
            if (subjectSelect) subjectSelect.value = "";
            if (divisionSelect) divisionSelect.value = "";
        }

        if (!isOther && titleInput) {
            titleInput.value = "";
        }
    }

    entryType.addEventListener("change", updateTimetableFields);
    updateTimetableFields();
}

/**
 * Filter semester options according to the selected department.
 *
 * Uses the existing server-rendered option labels:
 * "DEPARTMENT_CODE — Semester N"
 */
function initializeDepartmentSemesterFilters() {
    const filterPairs = [
        {
            departmentId: "divisionDepartment",
            semesterId: "divisionSemester"
        },
        {
            departmentId: "subjectDepartment",
            semesterId: "subjectSemester"
        }
    ];

    filterPairs.forEach(({ departmentId, semesterId }) => {
        const departmentSelect = document.getElementById(departmentId);
        const semesterSelect = document.getElementById(semesterId);

        if (!departmentSelect || !semesterSelect) return;

        const originalOptions = Array.from(semesterSelect.options).map(
            (option) => ({
                value: option.value,
                department: option.dataset.department || "",
                text: option.textContent,
                disabled: option.disabled,
                selected: option.selected
            })
        );

        function updateSemesters() {
            const departmentIdValue = departmentSelect.value;
            const departmentOption =
                departmentSelect.options[departmentSelect.selectedIndex];

            const departmentLabel = departmentOption
                ? departmentOption.textContent.trim()
                : "";

            const departmentCode = departmentLabel
                .split("—")[0]
                .trim()
                .toLowerCase();

            const previousValue = semesterSelect.value;

            semesterSelect.replaceChildren();

            originalOptions.forEach((optionData, index) => {
                const option = document.createElement("option");
                option.value = optionData.value;
                option.textContent = optionData.text;
                option.disabled = optionData.disabled;
                if (optionData.department) {
                    option.dataset.department = optionData.department;
                }

                if (index === 0 || optionData.value === "") {
                    semesterSelect.appendChild(option);
                    return;
                }

                const optionDepartmentCode = optionData.text
                    .split("—")[0]
                    .trim()
                    .toLowerCase();

                // Keep a semester only when its displayed department
                // code matches the selected department's code.
                const matchesDepartment =
                    departmentIdValue !== "" &&
                    (optionData.department
                        ? optionData.department === departmentIdValue
                        : departmentCode !== "" &&
                          optionDepartmentCode === departmentCode);

                if (matchesDepartment) {
                    semesterSelect.appendChild(option);
                }
            });

            const stillAvailable = Array.from(semesterSelect.options).some(
                (option) =>
                    option.value !== "" &&
                    option.value === previousValue
            );

            semesterSelect.value = stillAvailable ? previousValue : "";

            semesterSelect.disabled = departmentIdValue === "";
        }

        departmentSelect.addEventListener("change", updateSemesters);
        updateSemesters();
    });
}