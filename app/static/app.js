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
    };

    const syncUnitPriceFromAmount = () => {
      const qty = Number(quantityInput.value || 0);
      const amount = Number(amountInput.value || 0);
      if (unitPriceInput.dataset.manual === "1" || qty <= 0) {
        return;
      }
      if (amount <= 0) {
        unitPriceInput.value = "";
        return;
      }
      unitPriceInput.value = formatUnitPrice(amount / qty);
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
  });
}

function initBuyerAutocomplete() {
  const searchInput = document.getElementById("buyer-search");
  const buyerIdInput = document.getElementById("buyer-id-input");
  const datalist = document.getElementById("buyer-options");
  const buyerSelect = document.getElementById("buyer-select");
  const platformInput = document.getElementById("buyer-platform");
  const contactInput = document.getElementById("buyer-contact");

  if (!searchInput || !buyerIdInput || !datalist || !platformInput || !contactInput) {
    return;
  }

  let cached = [];
  let timer = null;
  const optionBuyersById = new Map();
  const optionBuyersByName = new Map();

  if (buyerSelect) {
    buyerSelect.querySelectorAll("option[value]").forEach((option) => {
      const id = String(option.value || "").trim();
      const name = String(option.dataset.name || option.textContent || "").trim();
      if (!id || !name) {
        return;
      }
      const buyer = {
        id: Number(id),
        name,
        platform: String(option.dataset.platform || ""),
        contact_person: String(option.dataset.contact || "")
      };
      optionBuyersById.set(id, buyer);
      optionBuyersByName.set(name, buyer);
    });
  }

  function renderOptions(data) {
    datalist.innerHTML = "";
    data.forEach((buyer) => {
      const option = document.createElement("option");
      option.value = buyer.name;
      option.label = `${buyer.name} | ${buyer.platform || "未分类"} | ${buyer.contact_person || "无联系人"} | ${buyer.contact_phone || "无手机"}`;
      datalist.appendChild(option);
    });
  }

  function applySelectedBuyer(hit) {
    buyerIdInput.value = String(hit.id);
    searchInput.value = hit.name || "";
    if (buyerSelect) {
      buyerSelect.value = String(hit.id);
    }
    platformInput.value = hit.platform || "";
    contactInput.value = hit.contact_person || "";
  }

  function bindSelectedByName(name) {
    const hit = cached.find((b) => b.name === name) || optionBuyersByName.get(name);
    if (!hit) {
      buyerIdInput.value = "";
      platformInput.value = "";
      contactInput.value = "";
      if (buyerSelect) {
        buyerSelect.value = "";
      }
      return;
    }
    applySelectedBuyer(hit);
  }

  async function searchBuyers(keyword) {
    const res = await fetch(`/api/buyers?q=${encodeURIComponent(keyword)}`);
    if (!res.ok) {
      return;
    }
    cached = await res.json();
    renderOptions(cached);
    bindSelectedByName(searchInput.value.trim());
  }

  searchInput.addEventListener("input", () => {
    const kw = searchInput.value.trim();
    if (timer) {
      clearTimeout(timer);
    }
    timer = setTimeout(() => {
      searchBuyers(kw);
    }, 180);
  });

  searchInput.addEventListener("change", () => {
    bindSelectedByName(searchInput.value.trim());
  });

  if (buyerSelect) {
    buyerSelect.addEventListener("change", () => {
      const selectedId = String(buyerSelect.value || "").trim();
      if (!selectedId) {
        buyerIdInput.value = "";
        searchInput.value = "";
        platformInput.value = "";
        contactInput.value = "";
        return;
      }
      const hit = optionBuyersById.get(selectedId) || cached.find((b) => String(b.id) === selectedId);
      if (hit) {
        applySelectedBuyer(hit);
      }
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
  if (initialId && buyerSelect && !buyerSelect.value) {
    buyerSelect.value = initialId;
  }
  if (buyerSelect && buyerSelect.value) {
    const initialHit = optionBuyersById.get(String(buyerSelect.value));
    if (initialHit && !searchInput.value.trim()) {
      searchInput.value = initialHit.name;
      platformInput.value = initialHit.platform || "";
      contactInput.value = initialHit.contact_person || "";
    }
  }

  searchBuyers(searchInput.value.trim());
}

function initBuyerFilterAutocomplete() {
  const select = document.getElementById("buyer-filter-select");
  const input = document.getElementById("buyer-filter-input");
  if (!select || !input) {
    return;
  }

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
  input.addEventListener("change", syncSelectFromInput);

  syncInputFromSelect();
}

function initInvoiceDetailModal() {
  const modal = document.getElementById("invoice-detail-modal");
  const closeBtn = document.getElementById("close-detail-modal");
  const itemsBody = document.getElementById("detail-items-body");
  const meta = document.getElementById("detail-invoice-meta");
  const triggers = document.querySelectorAll(".view-items");

  if (!modal || !closeBtn || !itemsBody || !meta || triggers.length === 0) {
    return;
  }

  function closeModal() {
    modal.classList.add("hidden");
    modal.style.display = "none";
    itemsBody.innerHTML = "";
  }

  closeBtn.addEventListener("click", closeModal);
  modal.addEventListener("click", (event) => {
    if (event.target === modal) {
      closeModal();
    }
  });

  triggers.forEach((btn) => {
    btn.addEventListener("click", async () => {
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
      meta.textContent = `发票号: ${data.invoice_number} | 类型: ${data.invoice_type}`;

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
  const fileInputs = invoiceForm.querySelectorAll(".invoice-file-input");
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

document.addEventListener("DOMContentLoaded", () => {
  initInvoicePage();
  initBuyerAutocomplete();
  initInvoiceDetailModal();
  initBuyerAiCreate();
  initStorageFolderPicker();
  initInvoiceFileActions();
  initInvoiceFileAutoRecognition();
  initAutoSubmitSelectForm();
  initBuyerFilterAutocomplete();
});
