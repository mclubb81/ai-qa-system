function pollJob(jobId) {
  var badge = document.getElementById("job-status-badge");
  var card = document.getElementById("job-card");
  if (!badge || !card) return;

  var interval = setInterval(function () {
    fetch("/api/jobs/" + jobId)
      .then(function (resp) {
        if (!resp.ok) {
          // Unknown job (404) -- nothing more will ever change here.
          clearInterval(interval);
          return null;
        }
        return resp.json();
      })
      .then(function (data) {
        if (!data) return;
        // Note: a job that itself FAILED also carries a (job-level) "error"
        // field in this same payload -- that's expected and not this case.
        if (data.status !== card.dataset.status) {
          card.dataset.status = data.status;
          badge.textContent = data.status;
          badge.className = "badge badge-" + data.status;
          if (data.status === "done" || data.status === "error") {
            clearInterval(interval);
            window.location.reload();
          }
        }
      })
      .catch(function () { clearInterval(interval); });
  }, 2000);
}

document.addEventListener("DOMContentLoaded", function () {
  var selectAll = document.getElementById("select-all");
  if (!selectAll) return;
  selectAll.addEventListener("change", function () {
    var name = selectAll.dataset.target;
    document.querySelectorAll('input[type="checkbox"][name="' + name + '"]').forEach(function (box) {
      box.checked = selectAll.checked;
    });
  });
});
