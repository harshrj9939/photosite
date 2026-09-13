const currency = new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR", maximumFractionDigits: 0 });
const framePrices = { "6x8": 899, "8x10": 1199, "12x16": 1499, "16x20": 1999 };
const productData = { everyday: { name: "The Everyday", price: 899 }, gallery: { name: "The Gallery", price: 1199 }, heritage: { name: "The Heritage", price: 1499 }, "brass-edit": { name: "The Brass Edit", price: 1699 } };
let cart = [];
let selectedColor = "walnut";
let selectedPhoto = null;
let publicConfig = { online_payments: false };

const $ = selector => document.querySelector(selector);
const $$ = selector => [...document.querySelectorAll(selector)];
const formatPrice = value => currency.format(value);

function setModal(element, open) {
  element.classList.toggle("open", open);
  document.body.classList.toggle("modal-open", !!document.querySelector(".modal.open"));
}

function cartTotal() { return cart.reduce((sum, item) => sum + (item.price * item.quantity), 0); }

function renderCart() {
  const container = $("#cartItems");
  const count = cart.reduce((sum, item) => sum + item.quantity, 0);
  $("#cartCount").textContent = count;
  $("#cartCount").dataset.empty = count === 0;
  $("#cartTotal").textContent = formatPrice(cartTotal());
  $("#checkoutButton").disabled = !cart.length;
  if (!cart.length) { container.innerHTML = '<p class="empty-cart">Your bag is waiting for a memory.</p>'; return; }
  container.innerHTML = cart.map((item, index) => `
    <div class="cart-row"><div class="cart-thumb">${item.preview ? `<img src="${item.preview}" alt="Custom frame preview">` : item.name}</div>
    <div class="cart-row-info"><h3>${item.name}</h3><p>${item.type === "custom" ? `${item.size.replace("x", " × ")} in · ${item.color}` : "Ready-to-style frame"}</p><button class="remove-item" data-remove="${index}">Remove</button></div><div class="cart-row-price">${formatPrice(item.price * item.quantity)}</div></div>`).join("");
  $$('[data-remove]').forEach(button => button.addEventListener("click", () => { cart.splice(Number(button.dataset.remove), 1); renderCart(); }));
}

function openCart() { $("#cartDrawer").classList.add("open"); $("#drawerBackdrop").classList.add("open"); $("#cartDrawer").setAttribute("aria-hidden", "false"); }
function closeCart() { $("#cartDrawer").classList.remove("open"); $("#drawerBackdrop").classList.remove("open"); $("#cartDrawer").setAttribute("aria-hidden", "true"); }
function addToCart(item) { cart.push({ ...item, quantity: 1 }); renderCart(); openCart(); }

function updateCustomPrice() { $("#customTotal").textContent = formatPrice(framePrices[$("#size").value]); }

function showOrderSuccess(orderNumber, paymentMethod) {
  $("#successMessage").textContent = paymentMethod === "cod"
    ? `Order ${orderNumber} is confirmed. Pay when it arrives, and we’ll email you your order updates.`
    : `Order ${orderNumber} is paid and confirmed. We’ll email you your order updates.`;
  setModal($("#successModal"), true);
}

function renderCheckout() {
  $("#checkoutItems").innerHTML = cart.map(item => `<div class="summary-row"><div><b>${item.name}</b><small>${item.type === "custom" ? `${item.size.replace("x", " × ")} in · ${item.color}` : "Ready-to-style frame"}</small></div><strong>${formatPrice(item.price * item.quantity)}</strong></div>`).join("");
  $("#checkoutTotal").textContent = formatPrice(cartTotal());
}

async function submitOrder(event) {
  event.preventDefault();
  const button = $("#placeOrder"); const error = $("#checkoutError"); error.textContent = "";
  const form = event.currentTarget; const formData = new FormData(form);
  const paymentMethod = formData.get("payment_method");
  const payloadItems = cart.map(item => item.type === "custom"
    ? { type: "custom", size: item.size, color: item.color, purpose: item.purpose, quantity: item.quantity }
    : { type: "product", product_id: item.product_id, quantity: item.quantity });
  formData.append("items", JSON.stringify(payloadItems));
  const customItem = cart.find(item => item.type === "custom" && item.file);
  if (customItem) formData.append("photo", customItem.file);
  button.disabled = true; button.textContent = paymentMethod === "razorpay" ? "Opening payment…" : "Placing order…";
  try {
    const response = await fetch("/api/orders", { method: "POST", body: formData }); const data = await response.json();
    if (!response.ok) throw new Error(data.error || "We couldn’t place the order. Please try again.");
    if (paymentMethod === "razorpay") { openRazorpay(data); return; }
    cart = []; renderCart(); setModal($("#checkoutModal"), false); showOrderSuccess(data.order_number, "cod");
  } catch (err) { error.textContent = err.message; button.disabled = false; button.innerHTML = 'Place order <span aria-hidden="true">→</span>'; }
}

function openRazorpay(order) {
  if (!window.Razorpay) { $("#checkoutError").textContent = "The payment window could not load. Please choose Cash on Delivery or try again."; $("#placeOrder").disabled = false; return; }
  const options = { key: order.razorpay.key, amount: order.amount * 100, currency: "INR", name: order.razorpay.name, description: order.razorpay.description, order_id: order.razorpay.order_id, prefill: { name: $("#name").value, email: $("#email").value, contact: $("#phone").value }, theme: { color: "#fa714b" }, handler: async response => {
    const verify = await fetch("/api/payments/razorpay/verify", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(response) }); const result = await verify.json();
    if (!verify.ok) { $("#checkoutError").textContent = result.error || "Payment verification failed. Please contact us with your payment ID."; return; }
    cart = []; renderCart(); setModal($("#checkoutModal"), false); showOrderSuccess(result.order_number, "razorpay");
  }, modal: { ondismiss: () => { $("#placeOrder").disabled = false; $("#placeOrder").innerHTML = 'Place order <span aria-hidden="true">→</span>'; } } };
  new Razorpay(options).open();
}

function setupCarousel() {
  const carousel = $("#carousel"); let index = 0;
  const update = () => { const card = carousel.querySelector(".product"); const visible = window.innerWidth > 560 ? 3 : 1; const max = Math.max(0, carousel.children.length - visible); index = Math.min(index, max); carousel.style.transform = `translateX(${-index * (card.getBoundingClientRect().width + 18)}px)`; };
  $("#next").addEventListener("click", () => { index = (index + 1) % (window.innerWidth > 560 ? 2 : 4); update(); });
  $("#prev").addEventListener("click", () => { const max = window.innerWidth > 560 ? 1 : 3; index = (index - 1 + max + 1) % (max + 1); update(); });
  window.addEventListener("resize", update); setInterval(() => { index = (index + 1) % (window.innerWidth > 560 ? 2 : 4); update(); }, 5500);
}

function setupTestimonials() {
  const notes = [["It’s become my favourite corner of the house. Looking at it just brings me right back to that day.","Aanya Mehta","Mumbai · The Heritage frame","https://images.unsplash.com/photo-1494790108377-be9c29b29330?auto=format&fit=crop&w=140&q=80"],["The frame arrived beautifully packed, and the print is even more vivid than I imagined.","Rohan Kapoor","Bengaluru · The Gallery frame","https://images.unsplash.com/photo-1500648767791-00dcc994a43e?auto=format&fit=crop&w=140&q=80"],["I gifted one to my parents and there were happy tears before the ribbon even hit the floor.","Naina Shah","Pune · The Everyday frame","https://images.unsplash.com/photo-1534528741775-53994a69daeb?auto=format&fit=crop&w=140&q=80"]]; let index = 0;
  setInterval(() => { index = (index + 1) % notes.length; const [quote,name,detail,image] = notes[index]; $("#quoteText").textContent = quote; $("#personName").textContent = name; $("#personDetail").textContent = detail; $("#personImage").src = image; }, 6500);
}

async function init() {
  try { publicConfig = await (await fetch("/api/config")).json(); } catch { /* COD remains available if offline. */ }
  if (!publicConfig.online_payments) { $("#razorpayOption").classList.add("disabled"); $("#razorpayOption input").disabled = true; $("#razorpayOption").title = "Online payments will be available when Razorpay is configured."; }
  renderCart(); setupCarousel(); setupTestimonials();
  $$(".open-customizer").forEach(button => button.addEventListener("click", event => { event.preventDefault(); setModal($("#customizer"), true); }));
  $("#modalClose").addEventListener("click", () => setModal($("#customizer"), false));
  $("#checkoutClose").addEventListener("click", () => setModal($("#checkoutModal"), false));
  $("#successClose").addEventListener("click", () => setModal($("#successModal"), false));
  $$(".modal").forEach(modal => modal.addEventListener("click", event => { if (event.target === modal) setModal(modal, false); }));
  $("#cartButton").addEventListener("click", openCart); $("#closeCart").addEventListener("click", closeCart); $("#drawerBackdrop").addEventListener("click", closeCart);
  $("#checkoutButton").addEventListener("click", () => { if (!cart.length) return; closeCart(); renderCheckout(); setModal($("#checkoutModal"), true); });
  $$(".swatch").forEach(swatch => swatch.addEventListener("click", () => { selectedColor = swatch.dataset.color; $$(".swatch").forEach(item => item.classList.remove("active")); swatch.classList.add("active"); const colors = { walnut:["#a26344","#6d3d28"], oak:["#e4ded0","#42453f"], charcoal:["#3e413d","#242624"], brass:["#c48a3f","#79501e"] }; $("#previewFrame").style.background = colors[selectedColor][0]; $("#previewFrame").style.borderColor = colors[selectedColor][1]; }));
  $("#size").addEventListener("change", updateCustomPrice);
  $("#photoUpload").addEventListener("change", event => { const file = event.target.files[0]; if (!file) return; if (file.size > 8 * 1024 * 1024) { event.target.value = ""; alert("Please upload a photo under 8 MB."); return; } selectedPhoto = file; const image = $("#previewImage"); image.src = URL.createObjectURL(file); image.style.display = "block"; $("#previewPlaceholder").style.display = "none"; });
  $("#customFrameForm").addEventListener("submit", event => { event.preventDefault(); const size = $("#size").value; addToCart({ type:"custom", name:"Custom photo frame", size, color:selectedColor, purpose:$("#purpose").value, price:framePrices[size], file:selectedPhoto, preview:selectedPhoto ? URL.createObjectURL(selectedPhoto) : null }); setModal($("#customizer"), false); });
  $$(".add-product").forEach(button => button.addEventListener("click", () => { const product = productData[button.dataset.product]; addToCart({ type:"product", product_id:button.dataset.product, name:product.name, price:product.price }); }));
  $("#checkoutForm").addEventListener("submit", submitOrder); $("#menuButton").addEventListener("click", () => { const links=$("#navLinks"); links.style.display = links.style.display === "flex" ? "none" : "flex"; });
  document.addEventListener("keydown", event => { if (event.key === "Escape") { $$(".modal.open").forEach(modal => setModal(modal, false)); closeCart(); } });
}
document.addEventListener("DOMContentLoaded", init);
