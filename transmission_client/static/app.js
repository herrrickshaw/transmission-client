const body = document.getElementById("torrents-body");
const addForm = document.getElementById("add-form");
const addSource = document.getElementById("add-source");

function humanSize(bytes) {
  const units = ["B", "KB", "MB", "GB", "TB"];
  let n = bytes;
  let i = 0;
  while (n >= 1024 && i < units.length - 1) {
    n /= 1024;
    i += 1;
  }
  return `${n.toFixed(1)}${units[i]}`;
}

function render(torrents) {
  if (!torrents.length) {
    body.innerHTML = '<tr><td colspan="7" class="empty">No torrents.</td></tr>';
    return;
  }
  body.innerHTML = torrents
    .map((t) => {
      const pct = Math.round(t.percentDone * 100);
      return `
        <tr data-id="${t.id}">
          <td>${escapeHtml(t.name)}</td>
          <td>${t.statusName}</td>
          <td>
            <div class="progress"><div style="width:${pct}%"></div></div>
            ${pct}%
          </td>
          <td>${humanSize(t.rateDownload)}/s</td>
          <td>${humanSize(t.rateUpload)}/s</td>
          <td>${humanSize(t.totalSize)}</td>
          <td class="actions">
            <button class="secondary" data-action="start">Start</button>
            <button class="secondary" data-action="stop">Stop</button>
            <button class="danger" data-action="remove">Remove</button>
          </td>
        </tr>`;
    })
    .join("");
}

function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str;
  return div.innerHTML;
}

async function refresh() {
  try {
    const res = await fetch("/api/torrents");
    const data = await res.json();
    render(data);
  } catch (err) {
    body.innerHTML = `<tr><td colspan="7" class="empty">Failed to load: ${err}</td></tr>`;
  }
}

body.addEventListener("click", async (event) => {
  const button = event.target.closest("button[data-action]");
  if (!button) return;
  const row = button.closest("tr");
  const id = row.dataset.id;
  const action = button.dataset.action;

  if (action === "start") await fetch(`/api/torrents/${id}/start`, { method: "POST" });
  if (action === "stop") await fetch(`/api/torrents/${id}/stop`, { method: "POST" });
  if (action === "remove") {
    if (!confirm("Remove this torrent?")) return;
    await fetch(`/api/torrents/${id}`, { method: "DELETE" });
  }
  refresh();
});

addForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const source = addSource.value.trim();
  if (!source) return;
  const res = await fetch("/api/torrents", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ source }),
  });
  if (res.ok) {
    addSource.value = "";
    refresh();
  } else {
    const data = await res.json();
    alert(`Failed to add torrent: ${data.error || res.statusText}`);
  }
});

refresh();
setInterval(refresh, 3000);
