// Progressive enhancement: filter the dealer list by city. The full list is already in the HTML.
(function () {
  var input = document.getElementById("city");
  var items = document.querySelectorAll("#dealer-list .dealer");
  if (!input || !items.length) return;
  input.addEventListener("input", function () {
    var q = input.value.trim().toLowerCase();
    items.forEach(function (li) {
      li.hidden = q !== "" && li.getAttribute("data-city").toLowerCase().indexOf(q) === -1;
    });
  });
})();
