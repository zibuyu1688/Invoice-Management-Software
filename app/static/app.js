function initInvoicePage() {
  const addBtn = document.getElementById("add-item");
  const tableBody = document.querySelector("#item-table tbody");
  if (!addBtn || !tableBody) {
    return;
  }

  const productNameOptionsNode = document.getElementById("product-name-options");
  const specMapNode = document.getElementById("product-spec-map");
  let productNameOptions = [];
  let productSpecsMap = {};

  try {
    productNameOptions = productNameOptionsNode ? JSON.parse(productNameOptionsNode.textContent || "[]") : [];
    productSpecsMap = specMapNode ? JSON.parse(specMapNode.textContent || "{}") : {};
  } catch (error) {
    productNameOptions = [];
    productSpecsMap = {};
  }

  function buildNameOptions(selectedName) {
    const parts = [];
    productNameOptions.forEach((name) => {
      const selected = selectedName === name ? " selected" : "";
      parts.push(`<option value="${name}"${selected}>${name}</option>`);
    });
    if (selectedName && productNameOptions.indexOf(selectedName) === -1) {
      parts.push(`<option value="${selectedName}" selected>${selectedName}</option>`);
    }
    return parts.join("");
  }

  function buildSpecOptions(productName, selectedSpec) {
    const parts = [];
    const specs = (productSpecsMap[productName] || []).filter(Boolean);
    specs.forEach((spec) => {
      const selected = selectedSpec === spec ? " selected" : "";
      parts.push(`<option value="${spec}"${selected}>${spec}</option>`);
    });
    if (selectedSpec && specs.indexOf(selectedSpec) === -1) {
      parts.push(`<option value="${selectedSpec}" selected>${selectedSpec}</option>`);
    }
    return parts.join("");
  }

  let rowSeq = 0;

  function setupNumericAutoClear(row) {
    row.querySelectorAll(".auto-clear-default").forEach((input) => {
      const defaultValue = input.dataset.defaultValue;
      if (defaultValue == null) {
        return;
      }
      input.addEventListener("focus", () => {
        if (input.dataset.cleared === "1") {
          return;
        }
        if (input.value === defaultValue) {
          input.value = "";
          input.dataset.cleared = "1";
        }
      });
    });
  }

  function formatAmount(value) {
    return Number(value || 0).toFixed(2);
  }

  function formatUnitPrice(value) {
    return Number(value || 0).toFixed(6).replace(/0+$/, "").replace(/\.$/, "");
  }

  function getCurrentTaxRate() {
    const taxRateSelect = document.querySelector('select[name="tax_rate"]');
    return Number(taxRateSelect ? taxRateSelect.value || 0 : 0);
  }

  function updateLineAmountMeta(row) {
    const amountInput = row.querySelector(".item-amount-input");
    const amountMeta = row.querySelector(".line-amount-meta");
    if (!amountInput || !amountMeta) {
      return;
    }

    const totalWithTax = Number(amountInput.value || 0);
    const taxRate = getCurrentTaxRate();
    const amountWithoutTax = totalWithTax > 0 ? totalWithTax / (1 + taxRate) : 0;
    const taxAmount = totalWithTax - amountWithoutTax;
    amountMeta.textContent = `未税 ${formatAmount(amountWithoutTax)} / 税额 ${formatAmount(taxAmount)}`;
  }

  function updateInvoiceSummaries() {
    const sellerSelect = document.getElementById("seller-select");
    const buyerSearch = document.getElementById("buyer-search");
    const taxRateSelect = document.querySelector('select[name="tax_rate"]');
    const statusSelect = document.querySelector('select[name="status"]');
    const sellerSummary = document.getElementById("summary-seller-name");
    const buyerSummary = document.getElementById("summary-buyer-name");
    const taxSummary = document.getElementById("summary-tax-rate");
    const statusSummary = document.getElementById("summary-invoice-status");
    const totalLines = document.getElementById("invoice-total-lines");
    const totalAmount = document.getElementById("invoice-total-amount");
    const totalTax = document.getElementById("invoice-total-tax");
    const totalWithTax = document.getElementById("invoice-total-with-tax");

    if (sellerSummary && sellerSelect) {
      const selectedOption = sellerSelect.options[sellerSelect.selectedIndex];
      sellerSummary.textContent = selectedOption ? (selectedOption.textContent || "未选择").trim() : "未选择";
    }
    if (buyerSummary && buyerSearch) {
      buyerSummary.textContent = buyerSearch.value.trim() || "未选择";
    }
    if (taxSummary && taxRateSelect) {
      taxSummary.textContent = `${Math.round(Number(taxRateSelect.value || 0) * 100)}%`;
    }
    if (statusSummary && statusSelect) {
      statusSummary.textContent = statusSelect.value || "未设置";
    }

    const rows = Array.from(tableBody.querySelectorAll("tr"));
    let grandWithoutTax = 0;
    let grandTax = 0;
    let grandWithTax = 0;
    rows.forEach((row) => {
      const amountInput = row.querySelector(".item-amount-input");
      const total = Number(amountInput ? amountInput.value || 0 : 0);
      const taxRate = getCurrentTaxRate();
      const withoutTax = total > 0 ? total / (1 + taxRate) : 0;
      const taxAmount = total - withoutTax;
      grandWithTax += total;
      grandWithoutTax += withoutTax;
      grandTax += taxAmount;
      updateLineAmountMeta(row);
    });

    if (totalLines) {
      totalLines.textContent = String(rows.length);
    }
    if (totalAmount) {
      totalAmount.textContent = formatAmount(grandWithoutTax);
    }
    if (totalTax) {
      totalTax.textContent = formatAmount(grandTax);
    }
    if (totalWithTax) {
      totalWithTax.textContent = formatAmount(grandWithTax);
    }
  }

  function bindLineAmountSync(row) {
    const unitPriceInput = row.querySelector(".item-unit-price-input");
    const quantityInput = row.querySelector(".item-quantity-input");
    const amountInput = row.querySelector(".item-amount-input");
    if (!unitPriceInput || !quantityInput || !amountInput) {
      return;
    }

    if (!unitPriceInput.dataset.manual) {
      unitPriceInput.dataset.manual = unitPriceInput.value.trim() ? "1" : "0";
    }

    const syncAmountFromUnitPrice = () => {
      const qty = Number(quantityInput.value || 0);
      const unitPrice = Number(unitPriceInput.value || 0);
      if (!unitPriceInput.value.trim() || qty <= 0) {
        return;
      }
      amountInput.value = formatAmount(unitPrice * qty);
      updateInvoiceSummaries();
    };

    const syncUnitPriceFromAmount = () => {
      const qty = Number(quantityInput.value || 0);
      const amount = Number(amountInput.value || 0);
      if (unitPriceInput.dataset.manual === "1" || qty <= 0) {
        return;
      }
      if (amount <= 0) {
        unitPriceInput.value = "";
        updateInvoiceSummaries();
        return;
      }
      unitPriceInput.value = formatUnitPrice(amount / qty);
      updateInvoiceSummaries();
    };

    unitPriceInput.addEventListener("input", () => {
      unitPriceInput.dataset.manual = unitPriceInput.value.trim() ? "1" : "0";
      if (unitPriceInput.dataset.manual === "1") {
        syncAmountFromUnitPrice();
      }
    });
    quantityInput.addEventListener("input", () => {
      if (unitPriceInput.value.trim()) {
        syncAmountFromUnitPrice();
      } else {
        syncUnitPriceFromAmount();
      }
    });
    amountInput.addEventListener("input", syncUnitPriceFromAmount);
    amountInput.addEventListener("input", updateInvoiceSummaries);
  }

  function setupRow(row) {
    rowSeq += 1;
    const nameInput = row.querySelector(".item-name-input");
    const specInput = row.querySelector(".item-spec-input");
    const nameList = row.querySelector(".item-name-list");
    const specList = row.querySelector(".item-spec-list");
    if (!nameInput || !specInput || !nameList || !specList) {
      return;
    }

    const rowKey = String(rowSeq);
    const nameListId = `item-name-list-${rowKey}`;
    const specListId = `item-spec-list-${rowKey}`;
    nameList.id = nameListId;
    specList.id = specListId;
    nameInput.setAttribute("list", nameListId);
    specInput.setAttribute("list", specListId);

    const selectedName = nameInput.dataset.selected || nameInput.value || "";
    const selectedSpec = specInput.dataset.selected || specInput.value || "";
    nameList.innerHTML = buildNameOptions(selectedName);
    nameInput.value = selectedName;
    specList.innerHTML = buildSpecOptions(selectedName, selectedSpec);
    specInput.value = selectedSpec;

    const refreshSpecList = () => {
      const currentSpec = specInput.value || "";
      specList.innerHTML = buildSpecOptions(nameInput.value, currentSpec);
    };

    nameInput.addEventListener("input", refreshSpecList);
    nameInput.addEventListener("change", refreshSpecList);

    setupNumericAutoClear(row);
    bindLineAmountSync(row);
    updateLineAmountMeta(row);
  }

  tableBody.querySelectorAll("tr").forEach(setupRow);

  addBtn.addEventListener("click", () => {
    const tr = document.createElement("tr");
    tr.innerHTML = [
      '<td><input name="item_name" class="item-name-input" list="" autocomplete="off" required><datalist class="item-name-list"></datalist></td>',
      '<td><input name="item_spec" class="item-spec-input" list="" autocomplete="off"><datalist class="item-spec-list"></datalist></td>',
      '<td><input name="item_unit_price" type="number" step="0.000001" min="0" class="item-unit-price-input" placeholder="选填"></td>',
      '<td><input name="item_quantity" type="number" step="1" min="1" value="1" class="auto-clear-default item-quantity-input" data-default-value="1" required></td>',
      '<td><input name="item_amount_with_tax" type="number" step="0.01" min="0" value="0" class="auto-clear-default item-amount-input" data-default-value="0" required></td>',
      '<td><button type="button" class="small-btn remove-row">删除</button></td>'
    ].join("");
    tableBody.appendChild(tr);
    setupRow(tr);
    updateInvoiceSummaries();
  });

  tableBody.addEventListener("click", (event) => {
    if (!event.target.classList.contains("remove-row")) {
      return;
    }
    const row = event.target.closest("tr");
    if (!row) {
      return;
    }
    if (tableBody.querySelectorAll("tr").length === 1) {
      return;
    }
    row.remove();
    updateInvoiceSummaries();
  });

  ["seller-select", "buyer-search"].forEach((id) => {
    const element = document.getElementById(id);
    if (element) {
      element.addEventListener("change", updateInvoiceSummaries);
      element.addEventListener("input", updateInvoiceSummaries);
    }
  });
  ["tax_rate", "status"].forEach((name) => {
    const element = document.querySelector(`[name="${name}"]`);
    if (element) {
      element.addEventListener("change", updateInvoiceSummaries);
    }
  });

  updateInvoiceSummaries();
}

function initSellerSalespersonSync() {
  const sellerSelect = document.getElementById("seller-select");
  const salespersonInput = document.getElementById("salesperson-input");
  const salespersonOptions = document.getElementById("salesperson-options");
  if (!sellerSelect || !salespersonInput) {
    return;
  }

  const baseOptions = salespersonOptions
    ? Array.from(salespersonOptions.querySelectorAll("option")).map((option) => (option.value || "").trim()).filter(Boolean)
    : [];

  let lastAutoValue = "";

  const renderSalespersonOptions = (sellerSalespeople) => {
    if (!salespersonOptions) {
      return;
    }
    const merged = [...sellerSalespeople];
    baseOptions.forEach((name) => {
      if (!merged.includes(name)) {
        merged.push(name);
      }
    });
    salespersonOptions.innerHTML = merged.map((name) => `<option value="${name}"></option>`).join("");
  };

  const applySellerSalesperson = () => {
    const selectedOption = sellerSelect.options[sellerSelect.selectedIndex];
    const sellerSalespeople = selectedOption
      ? String(selectedOption.dataset.salespeople || "").split("||").map((name) => name.trim()).filter(Boolean)
      : [];
    const defaultSalesperson = sellerSalespeople[0] || (selectedOption ? String(selectedOption.dataset.primarySalesperson || "").trim() : "");
    renderSalespersonOptions(sellerSalespeople);
    if (!salespersonInput.value.trim() || salespersonInput.value.trim() === lastAutoValue) {
      salespersonInput.value = defaultSalesperson;
    }
    lastAutoValue = defaultSalesperson;
  };

  sellerSelect.addEventListener("change", applySellerSalesperson);
  applySellerSalesperson();
}

function getTaskOverlay() {
  let overlay = document.getElementById("task-progress-overlay");
  if (overlay) {
    return overlay;
  }

  overlay = document.createElement("div");
  overlay.id = "task-progress-overlay";
  overlay.className = "task-progress-overlay";
  overlay.innerHTML = [
    '<div class="task-progress-card">',
    '<p class="section-kicker">Background Task</p>',
    '<h3 id="task-progress-title">处理中</h3>',
    '<p id="task-progress-message">请稍候...</p>',
    '<progress id="task-progress-bar" class="task-progress-bar" max="100" value="0"></progress>',
    '<div class="task-progress-meta">',
    '<span id="task-progress-status">任务已开始</span>',
    '<span id="task-progress-percent">0%</span>',
    '</div>',
    '</div>'
  ].join("");
  document.body.appendChild(overlay);
  return overlay;
}

function showTaskOverlay(title, message, progress) {
  const overlay = getTaskOverlay();
  overlay.classList.add("visible");
  document.getElementById("task-progress-title").textContent = title || "处理中";
  document.getElementById("task-progress-message").textContent = message || "请稍候...";
  document.getElementById("task-progress-bar").value = Number(progress || 0);
  document.getElementById("task-progress-percent").textContent = `${Number(progress || 0)}%`;
  document.getElementById("task-progress-status").textContent = message || "任务进行中";
}

function updateTaskOverlay(message, progress) {
  const overlay = getTaskOverlay();
  if (!overlay.classList.contains("visible")) {
    overlay.classList.add("visible");
  }
  document.getElementById("task-progress-message").textContent = message || "请稍候...";
  document.getElementById("task-progress-status").textContent = message || "任务进行中";
  document.getElementById("task-progress-bar").value = Number(progress || 0);
  document.getElementById("task-progress-percent").textContent = `${Number(progress || 0)}%`;
}

function hideTaskOverlay() {
  const overlay = document.getElementById("task-progress-overlay");
  if (overlay) {
    overlay.classList.remove("visible");
  }
}

async function pollBackgroundJob(jobId) {
  while (true) {
    const res = await fetch(`/api/jobs/${jobId}`);
    const data = await res.json();
    if (!res.ok) {
      throw new Error((data && (data.error || data.detail)) || "后台任务状态获取失败");
    }

    updateTaskOverlay(data.message || "任务执行中", data.progress || 0);

    if (data.status === "completed") {
      return data;
    }

    if (data.status === "failed") {
      throw new Error(data.error || "后台任务执行失败");
    }

    await new Promise((resolve) => window.setTimeout(resolve, 450));
  }
}

function initBuyerAutocomplete() {
  const searchInput = document.getElementById("buyer-search");
  const buyerIdInput = document.getElementById("buyer-id-input");
  const clearButton = document.getElementById("buyer-clear-btn");
  const datalist = document.getElementById("buyer-options");
  const platformInput = document.getElementById("buyer-platform");
  const contactInput = document.getElementById("buyer-contact");
  const invoiceTypeSelect = document.querySelector('[name="invoice_type"]');
  const taxRateSelect = document.querySelector('[name="tax_rate"]');

  if (!searchInput || !buyerIdInput || !datalist || !platformInput || !contactInput) {
    return;
  }

  let cached = [];
  let timer = null;
  const optionBuyersById = new Map();
  const optionBuyersByName = new Map();
  const buyerDefaultsCache = new Map();
  let invoiceTypeTouched = false;
  let taxRateTouched = false;

  const syncClearButtonState = () => {
    if (!clearButton) {
      return;
    }
    const hasValue = Boolean(searchInput.value.trim() || buyerIdInput.value.trim());
    clearButton.disabled = !hasValue;
    clearButton.hidden = !hasValue;
  };

  const clearSelectedBuyer = () => {
    buyerIdInput.value = "";
    searchInput.value = "";
    platformInput.value = "";
    contactInput.value = "";
    syncClearButtonState();
    searchInput.dispatchEvent(new Event("input", { bubbles: true }));
    searchInput.focus();
  };

  const setAutoFilledValue = (field, value) => {
    if (!field || value == null || value === "") {
      return;
    }
    field.dataset.autoFilling = "1";
    field.value = value;
    field.dispatchEvent(new Event("change", { bubbles: true }));
    window.setTimeout(() => {
      delete field.dataset.autoFilling;
    }, 0);
  };

  if (invoiceTypeSelect) {
    invoiceTypeSelect.addEventListener("change", () => {
      if (invoiceTypeSelect.dataset.autoFilling === "1") {
        return;
      }
      invoiceTypeTouched = true;
    });
  }

  if (taxRateSelect) {
    taxRateSelect.addEventListener("change", () => {
      if (taxRateSelect.dataset.autoFilling === "1") {
        return;
      }
      taxRateTouched = true;
    });
  }

  function cacheBuyer(buyer) {
    const id = String(buyer.id || "").trim();
    const name = String(buyer.name || "").trim();
    if (!id || !name) {
      return;
    }
    optionBuyersById.set(id, buyer);
    optionBuyersByName.set(name, buyer);
  }

  datalist.querySelectorAll("option[value]").forEach((option) => {
    const id = String(option.dataset.id || "").trim();
    const name = String(option.value || "").trim();
    if (!id || !name) {
      return;
    }
    cacheBuyer({
      id: Number(id),
      name,
      platform: String(option.dataset.platform || ""),
      contact_person: String(option.dataset.contact || ""),
      contact_phone: String(option.dataset.phone || "")
    });
  });

  function renderOptions(data) {
    datalist.innerHTML = "";
    data.forEach((buyer) => {
      cacheBuyer(buyer);
      const option = document.createElement("option");
      option.value = buyer.name;
      option.dataset.id = String(buyer.id);
      option.dataset.platform = buyer.platform || "";
      option.dataset.contact = buyer.contact_person || "";
      option.dataset.phone = buyer.contact_phone || "";
      option.label = `${buyer.name} | ${buyer.platform || "未分类"} | ${buyer.contact_person || "无联系人"} | ${buyer.contact_phone || "无手机"}`;
      datalist.appendChild(option);
    });
  }

  function applySelectedBuyer(hit) {
    buyerIdInput.value = String(hit.id);
    searchInput.value = hit.name || "";
    platformInput.value = hit.platform || "";
    contactInput.value = hit.contact_person || "";
    syncClearButtonState();
  }

  async function applyBuyerInvoiceDefaults(hit) {
    const buyerId = String(hit.id || "").trim();
    if (!buyerId || (!invoiceTypeSelect && !taxRateSelect)) {
      return;
    }

    let defaults = buyerDefaultsCache.get(buyerId);
    if (!defaults) {
      const res = await fetch(`/api/buyers/${encodeURIComponent(buyerId)}/invoice-defaults`);
      if (!res.ok) {
        return;
      }
      defaults = await res.json();
      buyerDefaultsCache.set(buyerId, defaults);
    }

    if (invoiceTypeSelect && !invoiceTypeTouched && defaults.default_invoice_type) {
      const matchedInvoiceType = Array.from(invoiceTypeSelect.options).find((option) => option.value === defaults.default_invoice_type);
      if (matchedInvoiceType) {
        setAutoFilledValue(invoiceTypeSelect, matchedInvoiceType.value);
      }
    }

    if (taxRateSelect && !taxRateTouched && defaults.default_tax_rate != null) {
      const normalizedRate = String(defaults.default_tax_rate);
      const matchedTaxRate = Array.from(taxRateSelect.options).find((option) => option.value === normalizedRate);
      if (matchedTaxRate) {
        setAutoFilledValue(taxRateSelect, matchedTaxRate.value);
      }
    }
  }

  async function bindSelectedByName(name, options = {}) {
    const hit = cached.find((b) => b.name === name) || optionBuyersByName.get(name);
    if (!hit) {
      buyerIdInput.value = "";
      platformInput.value = "";
      contactInput.value = "";
      syncClearButtonState();
      return;
    }
    applySelectedBuyer(hit);
    if (options.applyDefaults) {
      await applyBuyerInvoiceDefaults(hit);
    }
  }

  async function searchBuyers(keyword) {
    const res = await fetch(`/api/buyers?q=${encodeURIComponent(keyword)}`);
    if (!res.ok) {
      return;
    }
    cached = await res.json();
    renderOptions(cached);
    await bindSelectedByName(searchInput.value.trim());
  }

  searchInput.addEventListener("input", () => {
    const kw = searchInput.value.trim();
    syncClearButtonState();
    if (timer) {
      clearTimeout(timer);
    }
    timer = setTimeout(() => {
      searchBuyers(kw);
    }, 180);
  });

  searchInput.addEventListener("change", () => {
    bindSelectedByName(searchInput.value.trim(), { applyDefaults: true });
  });

  searchInput.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && searchInput.value.trim()) {
      event.preventDefault();
      clearSelectedBuyer();
    }
  });

  if (clearButton) {
    clearButton.addEventListener("click", () => {
      clearSelectedBuyer();
    });
  }

  const invoiceForm = document.getElementById("invoice-form");
  if (invoiceForm) {
    invoiceForm.addEventListener("submit", (event) => {
      if (!buyerIdInput.value) {
        event.preventDefault();
        alert("请从联想结果中选择有效的购买方");
      }
    });
  }

  const initialId = String(buyerIdInput.value || "").trim();
  if (initialId) {
    const initialHit = optionBuyersById.get(initialId);
    if (initialHit) {
      if (!searchInput.value.trim()) {
        searchInput.value = initialHit.name;
      }
      platformInput.value = initialHit.platform || "";
      contactInput.value = initialHit.contact_person || "";
    }
  }

  syncClearButtonState();
  searchBuyers(searchInput.value.trim());
}

function initBuyerFilterAutocomplete() {
  const select = document.getElementById("buyer-filter-select");
  const input = document.getElementById("buyer-filter-input");
  if (!select || !input) {
    return;
  }

  const form = select.closest("form");

  function syncInputFromSelect() {
    const selectedOption = select.options[select.selectedIndex];
    input.value = selectedOption && selectedOption.value ? (selectedOption.textContent || "").trim() : "";
  }

  function syncSelectFromInput() {
    const targetName = input.value.trim();
    if (!targetName) {
      select.value = "";
      return;
    }

    const match = Array.from(select.options).find((option) => {
      return (option.textContent || "").trim() === targetName;
    });
    select.value = match ? match.value : "";
  }

  select.addEventListener("change", syncInputFromSelect);
  input.addEventListener("change", () => {
    syncSelectFromInput();
    if (form) {
      form.submit();
    }
  });

  select.addEventListener("change", () => {
    syncInputFromSelect();
    if (form) {
      form.submit();
    }
  });

  syncInputFromSelect();
}

function initSellerFilterAutocomplete() {
  const select = document.getElementById("seller-filter-select");
  const input = document.getElementById("seller-filter-input");
  if (!select || !input) {
    return;
  }

  const form = select.closest("form");

  function syncInputFromSelect() {
    const selectedOption = select.options[select.selectedIndex];
    input.value = selectedOption && selectedOption.value ? (selectedOption.textContent || "").trim() : "";
  }

  function syncSelectFromInput() {
    const targetName = input.value.trim();
    if (!targetName) {
      select.value = "";
      return;
    }

    const match = Array.from(select.options).find((option) => {
      return (option.textContent || "").trim() === targetName;
    });
    select.value = match ? match.value : "";
  }

  select.addEventListener("change", () => {
    syncInputFromSelect();
    if (form) {
      form.submit();
    }
  });

  input.addEventListener("change", () => {
    syncSelectFromInput();
    if (form) {
      form.submit();
    }
  });

  syncInputFromSelect();
}

function initSalespersonFilterAutocomplete() {
  const select = document.getElementById("salesperson-filter-select");
  const input = document.getElementById("salesperson-filter-input");
  if (!select || !input) {
    return;
  }

  const form = select.closest("form");

  function syncInputFromSelect() {
    const selectedOption = select.options[select.selectedIndex];
    input.value = selectedOption && selectedOption.value ? (selectedOption.textContent || "").trim() : "";
  }

  function syncSelectFromInput() {
    const targetName = input.value.trim();
    if (!targetName) {
      select.value = "";
      return;
    }

    const match = Array.from(select.options).find((option) => {
      return (option.textContent || "").trim() === targetName;
    });
    select.value = match ? match.value : "";
  }

  select.addEventListener("change", () => {
    syncInputFromSelect();
    if (form) {
      form.submit();
    }
  });

  input.addEventListener("change", () => {
    syncSelectFromInput();
    if (form && select.value) {
      form.submit();
    }
  });

  syncInputFromSelect();
}

function initInvoiceDetailModal() {
  const modal = document.getElementById("invoice-detail-modal");
  const closeBtn = document.getElementById("close-detail-modal");
  const prevBtn = document.getElementById("detail-prev-btn");
  const nextBtn = document.getElementById("detail-next-btn");
  const positionMeta = document.getElementById("detail-position-meta");
  const itemsBody = document.getElementById("detail-items-body");
  const meta = document.getElementById("detail-invoice-meta");
  const voucherMeta = document.getElementById("detail-voucher-meta");
  const voucherPreview = document.getElementById("detail-voucher-preview");
  const triggers = document.querySelectorAll(".view-items");
  let currentIndex = -1;

  if (!modal || !closeBtn || !positionMeta || !itemsBody || !meta || !voucherMeta || !voucherPreview || !prevBtn || !nextBtn || triggers.length === 0) {
    return;
  }

  function closeModal() {
    modal.classList.add("hidden");
    modal.style.display = "none";
    itemsBody.innerHTML = "";
    voucherPreview.innerHTML = '<p class="muted-tip">暂无交易凭证文件</p>';
    document.body.style.overflow = "";
  }

  function updateNavState() {
    prevBtn.disabled = currentIndex <= 0;
    nextBtn.disabled = currentIndex >= triggers.length - 1;
    positionMeta.textContent = currentIndex >= 0 ? `固定序号 ${currentIndex + 1} / ${triggers.length}` : "";
  }

  function renderVoucherPreview(tradeVoucher, tradeVoucherText) {
    voucherPreview.innerHTML = "";

    if (tradeVoucher && tradeVoucher.is_image && tradeVoucher.url) {
      const image = document.createElement("img");
      image.className = "detail-voucher-preview-image";
      image.src = tradeVoucher.url;
      image.alt = tradeVoucher.name || "交易凭证预览";
      voucherPreview.appendChild(image);
    } else if (tradeVoucher && tradeVoucher.has_file) {
      const fileCard = document.createElement("div");
      fileCard.className = "detail-voucher-preview-card";
      fileCard.innerHTML = `<strong>${tradeVoucher.name || "交易凭证文件"}</strong><span>当前文件类型暂不支持内嵌预览，可在编辑页或列表中使用“打开 / 定位”操作。</span>`;
      voucherPreview.appendChild(fileCard);
    }

    if (tradeVoucherText) {
      const textCard = document.createElement("div");
      textCard.className = "detail-voucher-preview-card";
      textCard.innerHTML = `<strong>粘贴凭证内容</strong><span>${tradeVoucherText}</span>`;
      voucherPreview.appendChild(textCard);
    }

    if (!voucherPreview.children.length) {
      voucherPreview.innerHTML = '<p class="muted-tip">暂无交易凭证文件</p>';
    }
  }

  async function openInvoiceAt(index) {
    const btn = triggers[index];
    if (!btn) {
      return;
    }
    currentIndex = index;
    updateNavState();
    const invoiceId = btn.dataset.invoiceId;
    if (!invoiceId) {
      return;
    }

    const res = await fetch(`/api/invoices/${invoiceId}/items`);
    if (!res.ok) {
      alert("加载明细失败");
      return;
    }

    const data = await res.json();
    meta.textContent = `发票号: ${data.invoice_number} | 类型: ${data.invoice_type}${data.order_number ? ` | 订单号: ${data.order_number}` : ""}${data.order_date ? ` | 订单日期: ${data.order_date}` : ""}${data.salesperson ? ` | 业务员: ${data.salesperson}` : ""}`;
    voucherMeta.textContent = data.trade_voucher && data.trade_voucher.name ? `交易凭证文件：${data.trade_voucher.name}` : (data.trade_voucher_text ? "已填写粘贴凭证内容" : "未填写交易凭证");
    renderVoucherPreview(data.trade_voucher, data.trade_voucher_text);

    itemsBody.innerHTML = "";
    let subtotal = 0;
    let taxTotal = 0;
    let grandTotal = 0;
    data.items.forEach((item) => {
      subtotal += Number(item.amount || 0);
      taxTotal += Number(item.tax_amount || 0);
      grandTotal += Number(item.total_with_tax || 0);
      const tr = document.createElement("tr");
      tr.innerHTML = [
        `<td>${item.product_name ?? ""}</td>`,
        `<td>${item.spec_model ?? ""}</td>`,
        `<td>${item.tax_code ?? ""}</td>`,
        `<td>${item.quantity ?? ""}</td>`,
        `<td>${item.unit_price ?? ""}</td>`,
        `<td>${item.amount ?? ""}</td>`,
        `<td>${item.tax_rate ?? ""}</td>`,
        `<td>${item.tax_amount ?? ""}</td>`,
        `<td>${item.total_with_tax ?? ""}</td>`
      ].join("");
      itemsBody.appendChild(tr);
    });

    const subtotalTr = document.createElement("tr");
    subtotalTr.innerHTML = [
      '<td colspan="5"><strong>小计（不含税/税额）</strong></td>',
      `<td><strong>${subtotal.toFixed(2)}</strong></td>`,
      "<td>-</td>",
      `<td><strong>${taxTotal.toFixed(2)}</strong></td>`,
      "<td>-</td>"
    ].join("");
    itemsBody.appendChild(subtotalTr);

    const totalTr = document.createElement("tr");
    totalTr.innerHTML = [
      '<td colspan="8"><strong>合计（价税）</strong></td>',
      `<td><strong>${grandTotal.toFixed(2)}</strong></td>`
    ].join("");
    itemsBody.appendChild(totalTr);

    modal.classList.remove("hidden");
    modal.style.display = "flex";
    document.body.style.overflow = "hidden";
  }

  closeBtn.addEventListener("click", closeModal);
  prevBtn.addEventListener("click", () => {
    if (currentIndex > 0) {
      openInvoiceAt(currentIndex - 1);
    }
  });
  nextBtn.addEventListener("click", () => {
    if (currentIndex < triggers.length - 1) {
      openInvoiceAt(currentIndex + 1);
    }
  });
  modal.addEventListener("click", (event) => {
    if (event.target === modal) {
      closeModal();
    }
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !modal.classList.contains("hidden")) {
      closeModal();
    } else if (event.key === "ArrowUp" && !modal.classList.contains("hidden") && currentIndex > 0) {
      openInvoiceAt(currentIndex - 1);
    } else if (event.key === "ArrowDown" && !modal.classList.contains("hidden") && currentIndex < triggers.length - 1) {
      openInvoiceAt(currentIndex + 1);
    }
  });

  triggers.forEach((btn) => {
    btn.addEventListener("click", () => {
      openInvoiceAt(Array.from(triggers).indexOf(btn));
    });
  });
}

function initBuyerAiCreate() {
  const parseBtn = document.getElementById("buyer-ai-parse-btn");
  const input = document.getElementById("buyer-ai-input");
  const message = document.getElementById("buyer-ai-message");
  if (!parseBtn || !input || !message) {
    return;
  }

  const fieldMap = {
    name: document.getElementById("buyer-name"),
    tax_id: document.getElementById("buyer-tax-id"),
    address: document.getElementById("buyer-address"),
    bank_name: document.getElementById("buyer-bank-name"),
    bank_account_no: document.getElementById("buyer-bank-account-no"),
    contact_person: document.getElementById("buyer-contact-person"),
    contact_phone: document.getElementById("buyer-contact-phone"),
    wechat_qq: document.getElementById("buyer-wechat-qq"),
    shipping_address: document.getElementById("buyer-shipping-address"),
    platform: document.getElementById("buyer-platform"),
    notes: document.getElementById("buyer-notes")
  };

  parseBtn.addEventListener("click", async () => {
    const rawText = input.value.trim();
    if (!rawText) {
      message.textContent = "请先输入客户原始文本。";
      return;
    }

    parseBtn.disabled = true;
    message.textContent = "AI 正在分析，请稍候...";

    try {
      const formData = new FormData();
      formData.append("raw_text", rawText);

      const res = await fetch("/api/buyers/ai-parse", {
        method: "POST",
        body: formData
      });
      const data = await res.json();

      if (!res.ok || !data.ok) {
        message.textContent = (data && data.error) || "AI 解析失败";
        return;
      }

      const payload = data.data || {};
      Object.entries(fieldMap).forEach(([key, el]) => {
        if (!el) {
          return;
        }
        const value = payload[key];
        if (typeof value === "string" && value.trim()) {
          el.value = value.trim();
        }
      });

      message.textContent = "解析成功，字段已自动填充，请核对后保存。";
    } catch (error) {
      message.textContent = "调用 AI 服务失败，请稍后重试。";
    } finally {
      parseBtn.disabled = false;
    }
  });
}

function initBuyerWorkspace() {
  const workspace = document.querySelector("[data-buyer-workspace]");
  if (!workspace) {
    return;
  }

  const createDrawer = document.getElementById("buyer-create-drawer");
  const detailDrawer = document.getElementById("buyer-detail-drawer");
  const openCreateButtons = Array.from(document.querySelectorAll("[data-open-buyer-create]"));
  const closeButtons = Array.from(document.querySelectorAll("[data-close-buyer-modal]"));
  const filterForm = document.getElementById("buyer-filter-form");
  const liveFields = filterForm ? Array.from(filterForm.querySelectorAll("[data-live-submit]")) : [];
  const profileStatusInput = filterForm ? filterForm.querySelector("[data-profile-status-input]") : null;
  const profileFilterButtons = Array.from(document.querySelectorAll(".buyer-stat-filter"));
  const detailButtons = Array.from(document.querySelectorAll(".buyer-detail-trigger"));
  const rowActionMenus = Array.from(document.querySelectorAll(".row-action-menu"));
  const hoverCardTargets = Array.from(document.querySelectorAll("[data-hover-card-title]"));
  const detailName = document.getElementById("buyer-detail-name");
  const detailMeta = document.getElementById("buyer-detail-meta");
  const detailPlatform = document.getElementById("buyer-detail-platform");
  const detailTaxId = document.getElementById("buyer-detail-tax-id");
  const detailContactPerson = document.getElementById("buyer-detail-contact-person");
  const detailContactPhone = document.getElementById("buyer-detail-contact-phone");
  const detailWechatQq = document.getElementById("buyer-detail-wechat-qq");
  const detailAddress = document.getElementById("buyer-detail-address");
  const detailShippingAddress = document.getElementById("buyer-detail-shipping-address");
  const detailBankName = document.getElementById("buyer-detail-bank-name");
  const detailBankAccountNo = document.getElementById("buyer-detail-bank-account-no");
  const detailNotes = document.getElementById("buyer-detail-notes");
  const detailEditLink = document.getElementById("buyer-detail-edit-link");
  const createNameInput = document.getElementById("buyer-name");
  const createAiInput = document.getElementById("buyer-ai-input");
  let liveTimer = null;
  let hoverCard = null;

  function navigateBuyerFilters() {
    if (!filterForm) {
      return;
    }
    const params = new URLSearchParams();
    const formData = new FormData(filterForm);
    formData.forEach((value, key) => {
      const normalizedValue = typeof value === "string" ? value.trim() : String(value);
      if (!normalizedValue) {
        return;
      }
      params.set(key, normalizedValue);
    });
    const action = filterForm.getAttribute("action") || window.location.pathname;
    const query = params.toString();
    window.location.assign(query ? `${action}?${query}` : action);
  }

  function openModal(modal, focusTarget) {
    if (!modal) {
      return;
    }
    modal.classList.remove("hidden");
    document.body.classList.add("modal-open");
    if (focusTarget) {
      window.setTimeout(() => focusTarget.focus(), 50);
    }
  }

  function closeModal(modal) {
    if (!modal) {
      return;
    }
    modal.classList.add("hidden");
    if (
      (!createDrawer || createDrawer.classList.contains("hidden")) &&
      (!detailDrawer || detailDrawer.classList.contains("hidden"))
    ) {
      document.body.classList.remove("modal-open");
    }
  }

  openCreateButtons.forEach((button) => {
    button.addEventListener("click", () => {
      const preferredTarget = button.dataset.createFocus === "form" ? createNameInput : (createAiInput || createNameInput);
      openModal(createDrawer, preferredTarget);
    });
  });

  closeButtons.forEach((button) => {
    button.addEventListener("click", () => {
      closeModal(createDrawer);
      closeModal(detailDrawer);
    });
  });

  [createDrawer, detailDrawer].forEach((modal) => {
    if (!modal) {
      return;
    }
    modal.addEventListener("click", (event) => {
      if (event.target === modal) {
        closeModal(modal);
      }
    });
  });

  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape") {
      return;
    }
    closeModal(createDrawer);
    closeModal(detailDrawer);
  });

  if (filterForm && liveFields.length > 0) {
    liveFields.forEach((field) => {
      const eventName = field.tagName === "SELECT" ? "change" : "input";
      field.addEventListener(eventName, () => {
        if (field.tagName === "SELECT") {
          navigateBuyerFilters();
          return;
        }
        window.clearTimeout(liveTimer);
        liveTimer = window.setTimeout(() => {
          navigateBuyerFilters();
        }, 280);
      });
    });
  }

  if (filterForm && profileStatusInput && profileFilterButtons.length > 0) {
    profileFilterButtons.forEach((button) => {
      button.addEventListener("click", () => {
        profileStatusInput.value = button.dataset.profileFilter || "";
        navigateBuyerFilters();
      });
    });
  }

  function ensureHoverCard() {
    if (hoverCard) {
      return hoverCard;
    }
    hoverCard = document.createElement("div");
    hoverCard.className = "hover-card";
    hoverCard.innerHTML = '<p class="hover-card-title"></p><p class="hover-card-body"></p>';
    document.body.appendChild(hoverCard);
    return hoverCard;
  }

  function hideHoverCard() {
    if (!hoverCard) {
      return;
    }
    hoverCard.classList.remove("is-visible");
  }

  function positionHoverCard(target) {
    if (!hoverCard || !target) {
      return;
    }
    const rect = target.getBoundingClientRect();
    const top = rect.top - hoverCard.offsetHeight - 12;
    const left = Math.min(rect.left, window.innerWidth - hoverCard.offsetWidth - 16);
    hoverCard.style.top = `${Math.max(12, top)}px`;
    hoverCard.style.left = `${Math.max(12, left)}px`;
  }

  if (hoverCardTargets.length > 0) {
    hoverCardTargets.forEach((target) => {
      const showCard = () => {
        const title = target.dataset.hoverCardTitle || "";
        const body = target.dataset.hoverCardBody || "";
        if (!title || !body) {
          return;
        }
        const card = ensureHoverCard();
        const titleNode = card.querySelector(".hover-card-title");
        const bodyNode = card.querySelector(".hover-card-body");
        if (titleNode) {
          titleNode.textContent = title;
        }
        if (bodyNode) {
          bodyNode.textContent = body;
        }
        positionHoverCard(target);
        card.classList.add("is-visible");
      };

      target.addEventListener("mouseenter", showCard);
      target.addEventListener("focus", showCard);
      target.addEventListener("mouseleave", hideHoverCard);
      target.addEventListener("blur", hideHoverCard);
    });

    window.addEventListener("scroll", hideHoverCard, true);
    window.addEventListener("resize", hideHoverCard);
  }

  if (rowActionMenus.length > 0) {
    document.addEventListener("click", (event) => {
      rowActionMenus.forEach((menu) => {
        if (menu.contains(event.target)) {
          return;
        }
        menu.removeAttribute("open");
      });
    });
  }

  detailButtons.forEach((button) => {
    button.addEventListener("click", () => {
      const buyerId = button.dataset.buyerId || "";
      if (detailName) {
        detailName.textContent = button.dataset.name || "购买方详情";
      }
      if (detailMeta) {
        detailMeta.textContent = `${button.dataset.contactPerson || "未维护联系人"} · ${button.dataset.contactPhone || "未维护电话"}`;
      }
      if (detailPlatform) {
        detailPlatform.textContent = button.dataset.platform || "未分类";
      }
      if (detailTaxId) {
        detailTaxId.textContent = `税号：${button.dataset.taxId || "未维护"}`;
      }
      if (detailContactPerson) {
        detailContactPerson.textContent = button.dataset.contactPerson || "未维护";
      }
      if (detailContactPhone) {
        detailContactPhone.textContent = button.dataset.contactPhone || "未维护联系电话";
      }
      if (detailWechatQq) {
        detailWechatQq.textContent = button.dataset.wechatQq || "未维护";
      }
      if (detailAddress) {
        detailAddress.textContent = button.dataset.address || "未维护";
      }
      if (detailShippingAddress) {
        detailShippingAddress.textContent = button.dataset.shippingAddress || "未维护";
      }
      if (detailBankName) {
        detailBankName.textContent = button.dataset.bankName || "未维护";
      }
      if (detailBankAccountNo) {
        detailBankAccountNo.textContent = button.dataset.bankAccountNo || "未维护银行账号";
      }
      if (detailNotes) {
        detailNotes.textContent = button.dataset.notes || "未填写备注";
      }
      if (detailEditLink && buyerId) {
        detailEditLink.href = `/buyers/${buyerId}/edit`;
      }
      openModal(detailDrawer);
    });
  });
}

function initSellerWorkspace() {
  const workspace = document.querySelector("[data-seller-workspace]");
  if (!workspace) {
    return;
  }

  const drawer = document.getElementById("seller-members-drawer");
  const openButtons = Array.from(document.querySelectorAll("[data-open-seller-members]"));
  const closeButtons = Array.from(document.querySelectorAll("[data-close-seller-members]"));
  const form = document.getElementById("seller-members-form");
  const body = document.getElementById("seller-members-body");
  const title = document.getElementById("seller-members-title");
  const addRowBtn = document.getElementById("seller-add-member-row");
  const aiInput = document.getElementById("seller-ai-input");
  const aiParseBtn = document.getElementById("seller-ai-parse-btn");
  const aiMessage = document.getElementById("seller-ai-message");
  const bankNameDisplay = document.querySelector("[data-seller-bank-name-display]");
  const bankAccountDisplay = document.querySelector("[data-seller-bank-account-display]");
  const bankAccountHidden = document.querySelector("[data-seller-bank-account-hidden]");
  let hoverCard = null;

  function syncBankAccountField() {
    if (!bankAccountHidden) {
      return;
    }
    const bankName = bankNameDisplay ? bankNameDisplay.value.trim() : "";
    const bankNo = bankAccountDisplay ? bankAccountDisplay.value.trim() : "";
    bankAccountHidden.value = [bankName, bankNo].filter(Boolean).join(" ");
  }

  [bankNameDisplay, bankAccountDisplay].forEach((field) => {
    if (!field) {
      return;
    }
    field.addEventListener("input", syncBankAccountField);
  });
  syncBankAccountField();

  function buildMemberRow(member = {}) {
    const row = document.createElement("tr");
    row.innerHTML = [
      `<td><input name="member_name" value="${member.name || ""}" placeholder="姓名" required></td>`,
      `<td><input name="member_phone" value="${member.phone || ""}" placeholder="电话"></td>`,
      `<td><input name="member_wechat" value="${member.wechat || ""}" placeholder="微信"></td>`,
      `<td><input name="member_department" value="${member.department || ""}" placeholder="所属部门"></td>`,
      '<td><button type="button" class="small-btn seller-remove-member">删除</button></td>',
    ].join("");
    return row;
  }

  function renderMembers(members) {
    if (!body) {
      return;
    }
    body.innerHTML = "";
    const source = Array.isArray(members) && members.length > 0 ? members : [{}];
    source.forEach((member) => {
      body.appendChild(buildMemberRow(member));
    });
  }

  function openDrawer(button) {
    if (!drawer || !form) {
      return;
    }
    const sellerId = button.dataset.sellerId || "";
    const sellerName = button.dataset.sellerName || "销售方";
    let members = [];
    try {
      members = JSON.parse(button.dataset.sellerMembers || "[]");
    } catch (error) {
      members = [];
    }
    form.action = `/sellers/${sellerId}/salespeople`;
    if (title) {
      title.textContent = `${sellerName} · 业务员管理`;
    }
    renderMembers(members);
    drawer.classList.remove("hidden");
    document.body.classList.add("modal-open");
  }

  function closeDrawer() {
    if (!drawer) {
      return;
    }
    drawer.classList.add("hidden");
    document.body.classList.remove("modal-open");
  }

  openButtons.forEach((button) => {
    button.addEventListener("click", () => openDrawer(button));
  });

  closeButtons.forEach((button) => {
    button.addEventListener("click", closeDrawer);
  });

  if (drawer) {
    drawer.addEventListener("click", (event) => {
      if (event.target === drawer) {
        closeDrawer();
      }
    });
  }

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && drawer && !drawer.classList.contains("hidden")) {
      closeDrawer();
    }
  });

  if (addRowBtn && body) {
    addRowBtn.addEventListener("click", () => {
      body.appendChild(buildMemberRow());
    });
  }

  if (body) {
    body.addEventListener("click", (event) => {
      const target = event.target;
      if (!(target instanceof HTMLElement) || !target.classList.contains("seller-remove-member")) {
        return;
      }
      const row = target.closest("tr");
      if (row) {
        row.remove();
      }
      if (body.children.length === 0) {
        body.appendChild(buildMemberRow());
      }
    });
  }

  if (aiParseBtn && aiInput && aiMessage) {
    aiParseBtn.addEventListener("click", async () => {
      const rawText = aiInput.value.trim();
      if (!rawText) {
        aiMessage.textContent = "请先输入成员原始文本。";
        return;
      }
      aiParseBtn.disabled = true;
      aiMessage.textContent = "AI 正在识别成员，请稍候...";
      try {
        const formData = new FormData();
        formData.append("raw_text", rawText);
        const res = await fetch("/api/sellers/ai-parse-salespeople", {
          method: "POST",
          body: formData,
        });
        const data = await res.json();
        if (!res.ok || !data.ok) {
          aiMessage.textContent = (data && data.error) || "AI 成员识别失败";
          return;
        }
        renderMembers(data.data || []);
        aiMessage.textContent = "识别完成，请核对后保存成员。";
      } catch (error) {
        aiMessage.textContent = "调用 AI 成员识别失败，请稍后重试。";
      } finally {
        aiParseBtn.disabled = false;
      }
    });
  }

  function ensureHoverCard() {
    if (hoverCard) {
      return hoverCard;
    }
    hoverCard = document.createElement("div");
    hoverCard.className = "hover-card";
    hoverCard.innerHTML = '<p class="hover-card-title"></p><p class="hover-card-body"></p>';
    document.body.appendChild(hoverCard);
    return hoverCard;
  }

  function hideHoverCard() {
    if (hoverCard) {
      hoverCard.classList.remove("is-visible");
    }
  }

  Array.from(workspace.querySelectorAll("[data-hover-card-title]"))
    .forEach((target) => {
      const showCard = () => {
        const card = ensureHoverCard();
        const titleNode = card.querySelector(".hover-card-title");
        const bodyNode = card.querySelector(".hover-card-body");
        if (titleNode) {
          titleNode.textContent = target.dataset.hoverCardTitle || "";
        }
        if (bodyNode) {
          bodyNode.textContent = target.dataset.hoverCardBody || "";
        }
        const rect = target.getBoundingClientRect();
        card.style.top = `${Math.max(12, rect.top - card.offsetHeight - 12)}px`;
        card.style.left = `${Math.max(12, Math.min(rect.left, window.innerWidth - card.offsetWidth - 16))}px`;
        card.classList.add("is-visible");
      };
      target.addEventListener("mouseenter", showCard);
      target.addEventListener("focus", showCard);
      target.addEventListener("mouseleave", hideHoverCard);
      target.addEventListener("blur", hideHoverCard);
    });
}

function initStorageFolderPicker() {
  const pickerButtons = Array.from(document.querySelectorAll(".pick-folder-btn"));
  if (pickerButtons.length === 0) {
    return;
  }

  pickerButtons.forEach((pickerBtn) => {
    pickerBtn.addEventListener("click", async () => {
      const targetInputId = pickerBtn.dataset.targetInput || "";
      const targetMessageId = pickerBtn.dataset.messageId || "";
      const pathInput = targetInputId ? document.getElementById(targetInputId) : null;
      const message = targetMessageId ? document.getElementById(targetMessageId) : null;
      if (!pathInput || !message) {
        return;
      }

      pickerBtn.disabled = true;
      message.textContent = "正在打开文件夹选择窗口...";

      try {
        const res = await fetch("/api/settings/select-folder", {
          method: "POST"
        });
        const data = await res.json();

        if (!res.ok || !data.ok) {
          if (data && data.cancelled) {
            message.textContent = "已取消选择。";
            return;
          }
          message.textContent = (data && data.error) || "选择文件夹失败";
          return;
        }

        pathInput.value = data.path || "";
        message.textContent = "目录已选择，请点击“保存设置”生效。";
        pathInput.dispatchEvent(new Event("input", { bubbles: true }));
        showSettingsToast("路径已更新，保存后重启生效");
      } catch (error) {
        message.textContent = "打开文件夹选择失败，请重试。";
      } finally {
        pickerBtn.disabled = false;
      }
    });
  });
}

function initAutoSubmitSelectForm() {
  const form = document.querySelector(".auto-submit-select-form");
  if (!form) {
    return;
  }

  form.querySelectorAll("select").forEach((select) => {
    select.addEventListener("change", () => {
      form.submit();
    });
  });
}

function initInvoiceWorkbench() {
  const drawer = document.getElementById("invoice-filter-drawer");
  const toggleBtn = document.getElementById("toggle-filter-drawer-btn");
  if (!drawer) {
    return;
  }

  const workbenchForm = document.querySelector(".query-workbench-form");

  const storageKey = "invoice-filter-drawer-open";
  const hasQuery = window.location.search.length > 1;
  const savedState = window.localStorage.getItem(storageKey);

  if (!hasQuery && savedState === "0") {
    drawer.open = false;
  }

  drawer.addEventListener("toggle", () => {
    window.localStorage.setItem(storageKey, drawer.open ? "1" : "0");
  });

  if (toggleBtn) {
    toggleBtn.addEventListener("click", () => {
      drawer.open = !drawer.open;
    });
  }

  if (workbenchForm) {
    let keywordTimer = null;
    const recentRangeInput = workbenchForm.querySelector('input[name="recent_range"]');
    const startDateInput = workbenchForm.querySelector('input[name="start_date"]');
    const endDateInput = workbenchForm.querySelector('input[name="end_date"]');
    const submitWorkbenchForm = () => {
      if (typeof workbenchForm.requestSubmit === "function") {
        workbenchForm.requestSubmit();
        return;
      }
      workbenchForm.submit();
    };

    workbenchForm.querySelectorAll("[data-recent-range]").forEach((button) => {
      button.addEventListener("click", () => {
        if (recentRangeInput) {
          recentRangeInput.value = button.dataset.recentRange || "";
        }
        if (startDateInput) {
          startDateInput.value = "";
        }
        if (endDateInput) {
          endDateInput.value = "";
        }
        submitWorkbenchForm();
      });
    });

    workbenchForm.querySelectorAll('input[type="radio"]').forEach((input) => {
      input.addEventListener("change", () => {
        submitWorkbenchForm();
      });
    });

    workbenchForm.querySelectorAll('select[name="status"], input[type="date"]').forEach((field) => {
      field.addEventListener("change", () => {
        if (field.type === "date" && recentRangeInput) {
          recentRangeInput.value = "";
        }
        submitWorkbenchForm();
      });
    });

    const keywordInput = workbenchForm.querySelector('input[name="keyword"]');
    if (keywordInput) {
      keywordInput.addEventListener("input", () => {
        if (keywordTimer) {
          clearTimeout(keywordTimer);
        }
        keywordTimer = window.setTimeout(() => {
          submitWorkbenchForm();
        }, 320);
      });

      keywordInput.addEventListener("change", () => {
        if (keywordTimer) {
          clearTimeout(keywordTimer);
        }
        submitWorkbenchForm();
      });
    }
  }
}

function ensureSettingsToastStack() {
  let stack = document.querySelector(".settings-toast-stack");
  if (stack) {
    return stack;
  }

  stack = document.createElement("div");
  stack.className = "settings-toast-stack";
  document.body.appendChild(stack);
  return stack;
}

function showSettingsToast(message) {
  if (!message) {
    return;
  }

  const stack = ensureSettingsToastStack();
  const toast = document.createElement("div");
  toast.className = "settings-toast";
  const text = document.createElement("p");
  text.textContent = message;
  toast.appendChild(text);
  stack.appendChild(toast);

  window.setTimeout(() => {
    toast.remove();
    if (stack.childElementCount === 0) {
      stack.remove();
    }
  }, 2600);
}

function initSettingsFormState() {
  const forms = Array.from(document.querySelectorAll("[data-settings-form]"));
  if (forms.length === 0) {
    return;
  }

  forms.forEach((form) => {
    const submitButtons = Array.from(form.querySelectorAll('button[type="submit"]'));
    const trackedInputs = Array.from(form.querySelectorAll("input, textarea, select"));
    if (submitButtons.length === 0 || trackedInputs.length === 0) {
      return;
    }

    const computeDirty = () => trackedInputs.some((field) => {
      if (field.type === "checkbox" || field.type === "radio") {
        return field.checked !== field.defaultChecked;
      }
      const initialValue = field.dataset.initialValue;
      if (typeof initialValue === "string") {
        return field.value !== initialValue;
      }
      return field.value !== field.defaultValue;
    });

    const syncSubmitState = () => {
      const dirty = computeDirty();
      submitButtons.forEach((button) => {
        button.disabled = !dirty;
        button.classList.toggle("is-active", dirty);
      });
    };

    trackedInputs.forEach((field) => {
      field.addEventListener("input", syncSubmitState);
      field.addEventListener("change", syncSubmitState);
    });

    syncSubmitState();
  });
}

function initSettingsStorageAlert() {
  const storageInput = document.getElementById("storage-path-input");
  const alertBox = document.getElementById("storage-change-alert");
  const migrateCheckbox = document.getElementById("migrate-existing-data-checkbox");
  if (!storageInput || !alertBox) {
    return;
  }

  const initialValue = storageInput.dataset.initialValue || storageInput.defaultValue || "";

  const syncAlert = () => {
    const dirty = storageInput.value !== initialValue;
    alertBox.classList.toggle("is-hidden", !dirty);
    if (!dirty && migrateCheckbox) {
      migrateCheckbox.checked = false;
    }
  };

  storageInput.addEventListener("input", syncAlert);
  storageInput.addEventListener("change", syncAlert);
  syncAlert();
}

function initSettingsCollapse() {
  const toggleBtn = document.getElementById("settings-path-collapse-toggle");
  const content = document.getElementById("settings-path-collapse-content");
  if (!toggleBtn || !content) {
    return;
  }

  const syncState = (expanded) => {
    toggleBtn.setAttribute("aria-expanded", expanded ? "true" : "false");
    content.classList.toggle("is-collapsed", !expanded);
  };

  toggleBtn.addEventListener("click", () => {
    syncState(toggleBtn.getAttribute("aria-expanded") !== "true");
  });

  syncState(true);
}

function initSettingsCopyButtons() {
  const copyButtons = Array.from(document.querySelectorAll("[data-copy-text]"));
  if (copyButtons.length === 0) {
    return;
  }

  copyButtons.forEach((button) => {
    button.addEventListener("click", async () => {
      const text = button.dataset.copyText || "";
      if (!text) {
        return;
      }

      try {
        await navigator.clipboard.writeText(text);
        showSettingsToast("路径已复制");
      } catch (error) {
        showSettingsToast("复制失败，请手动复制");
      }
    });
  });
}

function initApiKeyVisibilityToggle() {
  const toggleBtn = document.getElementById("toggle-api-key-visibility");
  const input = document.getElementById("deepseek-api-key-input");
  if (!toggleBtn || !input) {
    return;
  }

  const syncState = () => {
    const visible = input.type === "text";
    toggleBtn.textContent = visible ? "◎" : "◉";
    toggleBtn.setAttribute("aria-label", visible ? "隐藏 API Key" : "显示 API Key");
  };

  toggleBtn.addEventListener("click", () => {
    input.type = input.type === "password" ? "text" : "password";
    syncState();
  });

  syncState();
}

function initSettingsSavedToasts() {
  const root = document.querySelector(".settings-page");
  if (!root) {
    return;
  }

  if (root.dataset.toastStoragePathsSaved === "1") {
    showSettingsToast("设置已保存，需重启生效");
    return;
  }

  if (root.dataset.toastSaved === "1") {
    showSettingsToast("设置已保存，需重启生效");
  }
  if (root.dataset.toastPathsSaved === "1") {
    showSettingsToast("目录设置已保存，需重启生效");
  }
  if (root.dataset.toastApiSaved === "1") {
    showSettingsToast("API Key 已保存");
  }
  if (root.dataset.toastBackupSaved === "1") {
    showSettingsToast("数据库备份已创建");
  }
}

function getSelectedCopyText(target) {
  if (target instanceof HTMLInputElement || target instanceof HTMLTextAreaElement) {
    const start = target.selectionStart;
    const end = target.selectionEnd;
    if (typeof start === "number" && typeof end === "number" && end > start) {
      return target.value.slice(start, end).trim();
    }
  }

  const selection = window.getSelection();
  const selectedText = selection ? String(selection.toString() || "").trim() : "";
  return selectedText;
}

function initGlobalCopyContextMenu() {
  if (window.__copyContextMenuInitialized) {
    return;
  }
  window.__copyContextMenuInitialized = true;

  let menu = null;
  let activeText = "";

  function ensureMenu() {
    if (menu) {
      return menu;
    }

    menu = document.createElement("div");
    menu.className = "copy-context-menu hidden";

    const copyButton = document.createElement("button");
    copyButton.type = "button";
    copyButton.className = "copy-context-menu-btn";
    copyButton.innerHTML = '<span>⧉</span><span>复制</span>';
    copyButton.addEventListener("click", async () => {
      if (!activeText) {
        return;
      }

      try {
        await navigator.clipboard.writeText(activeText);
        showSettingsToast("已复制选中文本");
      } catch (error) {
        showSettingsToast("复制失败，请重试");
      } finally {
        hideMenu();
      }
    });

    menu.appendChild(copyButton);
    document.body.appendChild(menu);
    return menu;
  }

  function hideMenu() {
    if (!menu) {
      return;
    }
    menu.classList.add("hidden");
    activeText = "";
  }

  document.addEventListener("contextmenu", (event) => {
    const selectedText = getSelectedCopyText(event.target);
    if (!selectedText) {
      hideMenu();
      return;
    }

    event.preventDefault();
    activeText = selectedText;

    const menuNode = ensureMenu();
    menuNode.classList.remove("hidden");

    const menuWidth = 148;
    const menuHeight = 58;
    const left = Math.min(event.clientX, window.innerWidth - menuWidth - 12);
    const top = Math.min(event.clientY, window.innerHeight - menuHeight - 12);
    menuNode.style.left = `${Math.max(12, left)}px`;
    menuNode.style.top = `${Math.max(12, top)}px`;
  });

  document.addEventListener("click", (event) => {
    if (menu && !menu.contains(event.target)) {
      hideMenu();
    }
  });

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      hideMenu();
    }
  });

  window.addEventListener("scroll", hideMenu, true);
  window.addEventListener("resize", hideMenu);
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", initGlobalCopyContextMenu, { once: true });
} else {
  initGlobalCopyContextMenu();
}

function initSidebarCollapse() {
  const toggleBtn = document.getElementById("sidebar-toggle-btn");
  if (!toggleBtn) {
    return;
  }

  const storageKey = "invoice-sidebar-collapsed";
  const root = document.body;

  function syncLabel() {
    const collapsed = root.classList.contains("sidebar-collapsed");
    toggleBtn.textContent = collapsed ? "⇥" : "⇤";
    toggleBtn.setAttribute("aria-label", collapsed ? "展开导航栏" : "收起导航栏");
  }

  if (window.localStorage.getItem(storageKey) === "1") {
    root.classList.add("sidebar-collapsed");
  }
  syncLabel();

  toggleBtn.addEventListener("click", () => {
    root.classList.toggle("sidebar-collapsed");
    window.localStorage.setItem(storageKey, root.classList.contains("sidebar-collapsed") ? "1" : "0");
    syncLabel();
  });
}

function initAsyncInvoiceSubmit() {
  const form = document.getElementById("invoice-form");
  if (!form) {
    return;
  }

  const endpoint = form.dataset.asyncJobEndpoint || "";
  if (!endpoint) {
    return;
  }

  form.addEventListener("submit", async (event) => {
    if (event.defaultPrevented) {
      return;
    }
    event.preventDefault();

    const submitBtn = form.querySelector('button[type="submit"]');
    const taskLabel = form.dataset.taskLabel || "发票归档与保存";
    const formData = new FormData(form);

    if (submitBtn) {
      submitBtn.disabled = true;
    }
    showTaskOverlay(taskLabel, "正在上传表单并创建后台任务", 8);

    try {
      const res = await fetch(endpoint, {
        method: "POST",
        body: formData
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok || !data.ok) {
        throw new Error((data && (data.error || data.detail)) || "提交后台任务失败");
      }

      updateTaskOverlay("后台任务已创建，正在处理附件和发票数据", 12);
      const job = await pollBackgroundJob(data.job_id);
      updateTaskOverlay(job.message || "任务已完成", 100);
      const redirectUrl = (job.result && job.result.redirect_url) || "/invoices";
      window.setTimeout(() => {
        window.location.href = redirectUrl;
      }, 250);
    } catch (error) {
      hideTaskOverlay();
      alert(error instanceof Error ? error.message : "后台任务执行失败");
      if (submitBtn) {
        submitBtn.disabled = false;
      }
    }
  });
}

function initAsyncExportTriggers() {
  const triggers = Array.from(document.querySelectorAll(".export-job-trigger"));
  if (triggers.length === 0) {
    return;
  }

  triggers.forEach((trigger) => {
    trigger.addEventListener("click", async (event) => {
      event.preventDefault();
      const href = trigger.getAttribute("href") || "/export.zip";
      const queryString = href.includes("?") ? href.slice(href.indexOf("?")) : "";

      showTaskOverlay("导出发票与凭证", "正在创建后台导出任务", 8);

      try {
        const res = await fetch(`/api/jobs/export-invoices${queryString}`, {
          method: "POST"
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok || !data.ok) {
          throw new Error((data && (data.error || data.detail)) || "创建导出任务失败");
        }

        updateTaskOverlay("后台导出任务已创建，正在生成图片压缩包", 14);
        const job = await pollBackgroundJob(data.job_id);
        const downloadUrl = job.result && job.result.download_url;
        if (!downloadUrl) {
          throw new Error("导出任务已完成，但未生成下载地址");
        }
        updateTaskOverlay(job.message || "导出完成", 100);
        window.setTimeout(() => {
          window.location.href = downloadUrl;
          hideTaskOverlay();
        }, 250);
      } catch (error) {
        hideTaskOverlay();
        alert(error instanceof Error ? error.message : "后台导出失败");
      }
    });
  });
}

function inferInvoiceNumberFromFilename(filename) {
  if (!filename) {
    return "";
  }

  const stem = filename.replace(/\.[^.]+$/, "");
  const digitGroups = stem.match(/\d{8,20}/g);
  if (digitGroups && digitGroups.length > 0) {
    return digitGroups[digitGroups.length - 1];
  }

  const tokenGroups = stem.match(/[A-Za-z0-9-]{6,}/g);
  if (tokenGroups && tokenGroups.length > 0) {
    return tokenGroups[tokenGroups.length - 1];
  }

  return "";
}

function initInvoiceFileAutoRecognition() {
  const invoiceForm = document.getElementById("invoice-form");
  if (!invoiceForm) {
    return;
  }

  const numberInput = invoiceForm.querySelector(".invoice-number-input");
  const fileInputs = invoiceForm.querySelectorAll('.invoice-file-input[data-invoice-number-source="1"]');
  if (!numberInput || fileInputs.length === 0) {
    return;
  }

  fileInputs.forEach((fileInput) => {
    fileInput.addEventListener("change", () => {
      if (!fileInput.files || fileInput.files.length === 0) {
        return;
      }
      if (numberInput.value.trim()) {
        return;
      }

      const inferred = inferInvoiceNumberFromFilename(fileInput.files[0].name || "");
      if (inferred) {
        numberInput.value = inferred;
      }
    });
  });
}

function initInvoiceFilePickerLabels() {
  const fileInputs = Array.from(document.querySelectorAll(".invoice-file-input"));
  if (fileInputs.length === 0) {
    return;
  }

  fileInputs.forEach((fileInput) => {
    const label = document.querySelector(`[data-file-name-for="${fileInput.id}"]`);
    const picker = label ? label.closest(".invoice-file-picker") : null;
    if (!label) {
      return;
    }

    const renderFileName = () => {
      if (fileInput.files && fileInput.files.length > 0) {
        label.textContent = Array.from(fileInput.files).map((file) => file.name).join("，");
      } else {
        label.textContent = "未选择文件";
      }
    };

    if (picker) {
      picker.addEventListener("click", () => {
        fileInput.click();
      });
    }

    fileInput.addEventListener("change", renderFileName);
    renderFileName();
  });
}

function initInvoiceFileActions() {
  const removeInput = document.getElementById("remove-invoice-file-input");
  const toggleBtn = document.getElementById("toggle-remove-file-btn");
  const hint = document.getElementById("remove-file-hint");
  const fileInput = document.getElementById("invoice-file-input");

  if (!removeInput || !toggleBtn || !hint) {
    return;
  }

  function renderRemoveState() {
    const pending = removeInput.value === "1";
    toggleBtn.classList.toggle("active", pending);
    toggleBtn.textContent = pending ? "取消删除" : "删除当前文件";
    hint.textContent = pending ? "已标记删除，保存后生效" : "未删除";
    hint.classList.toggle("pending", pending);
  }

  toggleBtn.addEventListener("click", () => {
    removeInput.value = removeInput.value === "1" ? "" : "1";
    renderRemoveState();
  });

  if (fileInput) {
    fileInput.addEventListener("change", () => {
      if (fileInput.files && fileInput.files.length > 0 && removeInput.value === "1") {
        hint.textContent = "已选择新文件，将执行替换";
      } else {
        renderRemoveState();
      }
    });
  }

  renderRemoveState();
}

function initInvoiceFileDropZone() {
  const dropZones = Array.from(document.querySelectorAll(".invoice-file-drop-zone"));
  if (dropZones.length === 0) {
    return;
  }

  function buildAcceptMatcher(acceptText) {
    const normalizedTokens = String(acceptText || "")
      .split(",")
      .map((item) => item.trim().toLowerCase())
      .filter(Boolean);

    if (normalizedTokens.length === 0) {
      return () => true;
    }

    return (file) => {
      const fileName = String(file && file.name ? file.name : "").toLowerCase();
      const mimeType = String(file && file.type ? file.type : "").toLowerCase();
      return normalizedTokens.some((token) => {
        if (token.startsWith(".")) {
          return fileName.endsWith(token);
        }
        if (token.endsWith("/*")) {
          return mimeType.startsWith(token.slice(0, -1));
        }
        return mimeType === token;
      });
    };
  }

  dropZones.forEach((dropZone) => {
    const targetInputId = dropZone.dataset.targetInput || "";
    const fileInput = targetInputId ? document.getElementById(targetInputId) : null;
    if (!fileInput) {
      return;
    }

    const acceptsFile = buildAcceptMatcher(fileInput.getAttribute("accept") || "");

    const assignFiles = (files) => {
      const pickedFiles = Array.from(files || []).filter((file) => acceptsFile(file));
      if (pickedFiles.length === 0) {
        alert("拖入的文件类型不在当前区域支持范围内，请改用该区域允许的格式。");
        return;
      }

      const transfer = new DataTransfer();
      pickedFiles.forEach((file) => transfer.items.add(file));
      fileInput.files = transfer.files;
      fileInput.dispatchEvent(new Event("change", { bubbles: true }));
    };

    dropZone.addEventListener("click", () => {
      fileInput.click();
    });

    ["dragenter", "dragover"].forEach((eventName) => {
      dropZone.addEventListener(eventName, (event) => {
        event.preventDefault();
        dropZone.classList.add("is-dragover");
      });
    });

    ["dragleave", "dragend", "drop"].forEach((eventName) => {
      dropZone.addEventListener(eventName, (event) => {
        event.preventDefault();
        dropZone.classList.remove("is-dragover");
      });
    });

    dropZone.addEventListener("drop", (event) => {
      assignFiles(event.dataTransfer ? event.dataTransfer.files : []);
    });
  });
}

function initNativeFileActions() {
  const actionButtons = Array.from(document.querySelectorAll(".native-file-action"));
  if (actionButtons.length === 0) {
    return;
  }

  actionButtons.forEach((button) => {
    button.addEventListener("click", async () => {
      const endpoint = button.dataset.endpoint || "";
      if (!endpoint) {
        return;
      }

      button.disabled = true;
      button.classList.add("is-loading");

      try {
        const res = await fetch(endpoint, {
          method: "POST"
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok || !data.ok) {
          showSettingsToast((data && (data.error || data.detail)) || "系统文件操作失败");
          return;
        }
        showSettingsToast((data && data.message) || "操作已执行");
      } catch (error) {
        showSettingsToast("系统文件操作失败，请稍后重试。");
      } finally {
        button.disabled = false;
        button.classList.remove("is-loading");
      }
    });
  });
}

document.addEventListener("DOMContentLoaded", () => {
  initSidebarCollapse();
  initInvoicePage();
  initSellerSalespersonSync();
  initSellerWorkspace();
  initBuyerAutocomplete();
  initInvoiceDetailModal();
  initBuyerAiCreate();
  initBuyerWorkspace();
  initStorageFolderPicker();
  initInvoiceFileActions();
  initInvoiceFileAutoRecognition();
  initInvoiceFilePickerLabels();
  initInvoiceFileDropZone();
  initNativeFileActions();
  initSettingsFormState();
  initSettingsStorageAlert();
  initSettingsCollapse();
  initSettingsCopyButtons();
  initApiKeyVisibilityToggle();
  initSettingsSavedToasts();
  initAutoSubmitSelectForm();
  initInvoiceWorkbench();
  initAsyncInvoiceSubmit();
  initAsyncExportTriggers();
  initSellerFilterAutocomplete();
  initBuyerFilterAutocomplete();
  initSalespersonFilterAutocomplete();
});
