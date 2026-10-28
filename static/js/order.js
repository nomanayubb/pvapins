(function () {
  var box = document.getElementById("order");
  if (!box) return;
  var url = box.dataset.statusUrl;
  var isRent = box.dataset.rent === "1";
  var delays = [3000, 3000, 4000, 5000, 6000, 8000]; // gentle backoff
  var tries = 0, remaining = null, timerEl = document.getElementById("timer");

  function esc(s) { var d = document.createElement("div"); d.textContent = s == null ? "" : s; return d.innerHTML; }

  function paint(d) {
    document.getElementById("status").textContent = d.status_label;
    document.getElementById("status").className = "badge st-" + d.status;
    document.getElementById("refunded").hidden = !d.refunded;
    if (d.otp) document.getElementById("otp").textContent = d.otp;
    document.getElementById("otp-msg").textContent = d.message || "";
    if (isRent) {
      var body = document.getElementById("msgs");
      if (body && d.messages && d.messages.length) {
        body.innerHTML = d.messages.map(function (m) {
          return "<tr><td>" + esc(m.from) + "</td><td>" + esc(m.message) + "</td><td>" + esc(m.timestamp) + "</td></tr>";
        }).join("");
      }
    }
    remaining = d.remaining;
  }

  function tick() {
    if (remaining == null || !timerEl) return;
    var m = Math.floor(remaining / 60), s = remaining % 60;
    timerEl.textContent = remaining > 0 ? "⏱ " + m + ":" + (s < 10 ? "0" : "") + s : "";
    if (remaining > 0) remaining -= 1;
  }
  setInterval(tick, 1000);

  function poll() {
    fetch(url, { credentials: "same-origin", headers: { Accept: "application/json" } })
      .then(function (r) { return r.ok ? r.json() : Promise.reject(); })
      .then(function (d) {
        paint(d);
        // temp orders stop on any final state; rentals keep listening while active
        var done = isRent ? d.status !== "active" : d.status !== "active";
        if (done) { if (d.status === "expired" || d.status === "completed") location.reload(); return; }
        tries += 1;
        setTimeout(poll, delays[Math.min(tries, delays.length - 1)]);
      })
      .catch(function () { setTimeout(poll, 8000); });
  }

  if (box.dataset.status === "active") poll();
})();
