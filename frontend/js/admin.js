Auth.guard("admin");
document.getElementById("whoName").textContent = Auth.fullName() || "Administrator";

let departmentsCache = [];
let subjectsCache = [];
let facultyCache = [];
let currentPeopleRole = "faculty";

// ---------------- Navigation ----------------
document.querySelectorAll("#sideNav a").forEach((link) => {
  link.addEventListener("click", (e) => {
    e.preventDefault();
    document.querySelectorAll("#sideNav a").forEach((a) => a.classList.remove("active"));
    link.classList.add("active");
    document.querySelectorAll(".main > section").forEach((s) => (s.style.display = "none"));
    const section = document.getElementById(`sec-${link.dataset.section}`);
    section.style.display = "block";
    loadSection(link.dataset.section);
  });
});

function loadSection(name) {
  if (name === "overview") loadOverview();
  if (name === "departments") loadDepartments();
  if (name === "subjects") loadSubjects();
  if (name === "people") loadPeople();
  if (name === "allocations") loadAllocations();
}

function openModal(id) { document.getElementById(id).classList.add("open"); }
function closeModal(id) { document.getElementById(id).classList.remove("open"); }

// ---------------- Overview ----------------
async function loadOverview() {
  try {
    const rows = await Api.get("/api/admin/attendance/overview");
    const present = rows.filter((r) => r.status === "present").length;
    const total = rows.length;
    const pct = total ? Math.round((present / total) * 100) : 0;

    document.getElementById("statRow").innerHTML = `
      <div class="stat-block"><div class="num">${total}</div><div class="label">Attendance records</div></div>
      <div class="stat-block good"><div class="num">${present}</div><div class="label">Marked present</div></div>
      <div class="stat-block"><div class="num">${pct}%</div><div class="label">Overall attendance rate</div></div>
    `;

    const tbody = document.querySelector("#overviewTable tbody");
    tbody.innerHTML = rows.length
      ? rows.map((r) => `<tr><td class="num">#${r.student_profile_id}</td><td>${r.subject_name}</td><td>${r.division}</td><td>${r.scheduled_date}</td><td>${statusPill(r.status)}</td></tr>`).join("")
      : `<tr><td colspan="5" class="empty-state">No attendance recorded yet.</td></tr>`;
  } catch (err) {
    document.getElementById("statRow").innerHTML = "";
    document.querySelector("#overviewTable tbody").innerHTML = `<tr><td colspan="5" class="empty-state">${err.message}</td></tr>`;
  }
}

// ---------------- Departments ----------------
async function loadDepartments() {
  departmentsCache = await Api.get("/api/admin/departments");
  const tbody = document.querySelector("#deptTable tbody");
  tbody.innerHTML = departmentsCache.length
    ? departmentsCache.map((d) => `<tr><td class="num">${d.department_id}</td><td>${d.department_name}</td><td>${d.description || "—"}</td></tr>`).join("")
    : `<tr><td colspan="3" class="empty-state">No departments yet — create one to get started.</td></tr>`;
  populateDeptSelects();
}

function populateDeptSelects() {
  const opts = departmentsCache.map((d) => `<option value="${d.department_id}">${d.department_name}</option>`).join("");
  ["subjDept", "uDept", "allocSubjDeptFilter"].forEach((id) => {
    const el = document.getElementById(id);
    if (el) el.innerHTML = opts || `<option value="">No departments yet</option>`;
  });
}

document.getElementById("deptForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  try {
    await Api.post("/api/admin/departments", {
      department_name: document.getElementById("deptName").value.trim(),
      description: document.getElementById("deptDesc").value.trim() || null,
    });
    document.getElementById("deptForm").reset();
    closeModal("deptModal");
    loadDepartments();
  } catch (err) { showError(document.getElementById("deptErr"), err); }
});

// ---------------- Subjects ----------------
async function loadSubjects() {
  if (!departmentsCache.length) await loadDepartments();
  subjectsCache = await Api.get("/api/admin/subjects");
  const deptName = (id) => departmentsCache.find((d) => d.department_id === id)?.department_name || "—";
  const tbody = document.querySelector("#subjTable tbody");
  tbody.innerHTML = subjectsCache.length
    ? subjectsCache.map((s) => `<tr><td class="num">${s.subject_code}</td><td>${s.subject_name}</td><td>${s.semester}</td><td>${deptName(s.department_id)}</td><td>${s.total_sessions_conducted}</td></tr>`).join("")
    : `<tr><td colspan="5" class="empty-state">No subjects yet.</td></tr>`;
}

document.getElementById("subjForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  try {
    await Api.post("/api/admin/subjects", {
      subject_code: document.getElementById("subjCode").value.trim(),
      subject_name: document.getElementById("subjName").value.trim(),
      semester: parseInt(document.getElementById("subjSem").value, 10),
      department_id: parseInt(document.getElementById("subjDept").value, 10),
    });
    document.getElementById("subjForm").reset();
    closeModal("subjModal");
    loadSubjects();
  } catch (err) { showError(document.getElementById("subjErr"), err); }
});

// ---------------- People (Faculty / Students) ----------------
function switchPeopleTab(role) {
  currentPeopleRole = role;
  document.querySelectorAll("#sec-people .tabs button").forEach((b) => b.classList.toggle("active", b.dataset.role === role));
  document.getElementById("peopleTitle").textContent = role === "faculty" ? "Faculty" : "Students";
  document.getElementById("studentOnlyFields").style.display = role === "student" ? "block" : "none";
  document.getElementById("uRole").value = role;
  loadPeople();
}

async function loadPeople() {
  if (!departmentsCache.length) await loadDepartments();
  const people = await Api.get(`/api/admin/users?role=${currentPeopleRole}`);
  if (currentPeopleRole === "faculty") facultyCache = people;
  const deptName = (id) => departmentsCache.find((d) => d.department_id === id)?.department_name || "—";

  const tbody = document.querySelector("#peopleTable tbody");
  tbody.innerHTML = people.length
    ? people.map((p) => `
        <tr>
          <td class="num" style="font-weight:600;">#${p.profile_id}</td>
          <td>${p.full_name}</td>
          <td class="mono" style="font-size:13px;">${p.email}</td>
          <td class="num">${p.internal_id || "—"}</td>
          <td>${deptName(p.department_id)}</td>
          <td class="num">${p.current_semester ? `Sem ${p.current_semester} · ${p.division_section || "—"}` : "—"}</td>
          <td><button class="btn-danger btn-sm" onclick="removePerson(${p.profile_id})">Remove</button></td>
        </tr>`).join("")
    : `<tr><td colspan="6" class="empty-state">No ${currentPeopleRole} accounts yet.</td></tr>`;
}

async function removePerson(profileId) {
  if (!confirm("Remove this account? This cannot be undone.")) return;
  await Api.del(`/api/admin/users/${profileId}`);
  loadPeople();
}

document.getElementById("userForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  try {
    await Api.post("/api/admin/users", {
      email: document.getElementById("uEmail").value.trim(),
      password: document.getElementById("uPassword").value,
      role: document.getElementById("uRole").value,
      full_name: document.getElementById("uName").value.trim(),
      department_id: document.getElementById("uDept").value ? parseInt(document.getElementById("uDept").value, 10) : null,
      internal_id: document.getElementById("uInternalId").value.trim() || null,
      current_semester: document.getElementById("uSemester").value ? parseInt(document.getElementById("uSemester").value, 10) : null,
      division_section: document.getElementById("uDivision").value.trim() || null,
    });
    document.getElementById("userForm").reset();
    closeModal("userModal");
    loadPeople();
  } catch (err) { showError(document.getElementById("userErr"), err); }
});

// ---------------- Class Allocation ----------------
async function loadAllocations() {
  if (!subjectsCache.length) await loadSubjects();
  if (!facultyCache.length) facultyCache = await Api.get("/api/admin/users?role=faculty");

  document.getElementById("allocSubj").innerHTML = subjectsCache.map((s) => `<option value="${s.subject_id}">${s.subject_code} — ${s.subject_name}</option>`).join("") || `<option value="">Create a subject first</option>`;
  document.getElementById("allocFac").innerHTML = facultyCache.map((f) => `<option value="${f.profile_id}">${f.full_name}</option>`).join("") || `<option value="">Add faculty first</option>`;

  const allocations = await Api.get("/api/admin/class-allocations");
  const subjName = (id) => subjectsCache.find((s) => s.subject_id === id)?.subject_name || "—";
  const facName = (id) => facultyCache.find((f) => f.profile_id === id)?.full_name || `#${id}`;

  const tbody = document.querySelector("#allocTable tbody");
  tbody.innerHTML = allocations.length
    ? allocations.map((a) => `<tr><td>${subjName(a.subject_id)}</td><td>${facName(a.faculty_profile_id)}</td><td class="num">${a.assigned_semester}</td><td class="num">${a.assigned_division}</td></tr>`).join("")
    : `<tr><td colspan="4" class="empty-state">No classes assigned yet.</td></tr>`;
}

document.getElementById("allocForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  try {
    await Api.post("/api/admin/class-allocations", {
      subject_id: parseInt(document.getElementById("allocSubj").value, 10),
      faculty_profile_id: parseInt(document.getElementById("allocFac").value, 10),
      assigned_semester: parseInt(document.getElementById("allocSem").value, 10),
      assigned_division: document.getElementById("allocDiv").value.trim(),
    });
    document.getElementById("allocForm").reset();
    closeModal("allocModal");
    loadAllocations();
  } catch (err) { showError(document.getElementById("allocErr"), err); }
});

// ---------------- Reports ----------------
async function exportReport(format) {
  const res = await fetch(`/api/admin/reports/export?format=${format}`, {
    headers: { Authorization: `Bearer ${Auth.token()}` },
  });
  if (!res.ok) { alert("No attendance data available to export yet."); return; }
  const blob = await res.blob();
  const url = window.URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `attendance_report.${format}`;
  a.click();
  window.URL.revokeObjectURL(url);
}

// ---------------- Init ----------------
loadOverview();
