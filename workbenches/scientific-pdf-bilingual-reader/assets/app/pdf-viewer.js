import {
  GlobalWorkerOptions,
  RenderingCancelledException,
  TextLayer,
  getDocument,
} from "/vendor/pdfjs/pdf.mjs";

GlobalWorkerOptions.workerSrc = "/vendor/pdfjs/pdf.worker.mjs";

const viewer = document.querySelector("#pdfViewer");
const viewportElement = document.querySelector("#pdfPageViewport");
const pageShell = document.querySelector("#pdfPageShell");
const canvas = document.querySelector("#pdfCanvas");
const textLayerElement = document.querySelector("#pdfTextLayer");
const loadingElement = document.querySelector("#pdfLoading");
const thumbnailList = document.querySelector("#thumbnailList");
const thumbnailFold = document.querySelector("#thumbnailFold");
const zoomValue = document.querySelector("#zoomValue");

let documentHandle = null;
let loadingTask = null;
let sourceUrl = null;
let currentPage = 1;
let currentScale = 1;
let zoomMode = "fit";
let renderTask = null;
let textLayer = null;
let renderVersion = 0;
let resizeTimer = null;
let thumbnailObserver = null;
let thumbnailQueue = Promise.resolve();
let observedViewportWidth = 0;

function setLoading(message, error = false) {
  loadingElement.textContent = message;
  loadingElement.classList.toggle("error", error);
  loadingElement.hidden = false;
  pageShell.hidden = true;
}

function hideLoading() {
  loadingElement.hidden = true;
  pageShell.hidden = false;
}

function setThumbnailOpen(open) {
  const isOpen = Boolean(open);
  viewer.classList.toggle("thumbnails-collapsed", !isOpen);
  thumbnailFold.setAttribute("aria-expanded", String(isOpen));
  thumbnailFold.title = isOpen ? "收起页面缩略图" : "展开页面缩略图";
  thumbnailFold.querySelector("[aria-hidden]").textContent = isOpen ? "‹" : "›";
  thumbnailFold.querySelector(".sr-only").textContent = thumbnailFold.title;
  localStorage.setItem("pdf-reader-thumbnails-open", String(isOpen));
  if (zoomMode === "fit" && documentHandle) scheduleFitRender();
}

function updateZoomLabel() {
  zoomValue.textContent = zoomMode === "fit" ? "适宽" : `${Math.round(currentScale * 100)}%`;
}

function activeThumbnail() {
  thumbnailList.querySelectorAll(".thumbnail-item").forEach((item) => {
    const active = Number(item.dataset.page) === currentPage;
    item.classList.toggle("active", active);
    item.setAttribute("aria-current", active ? "page" : "false");
    if (active) item.scrollIntoView({ block: "nearest" });
  });
}

function dispatchPageChange(source) {
  window.dispatchEvent(new CustomEvent("pdf-page-change", {
    detail: { page: currentPage, pages: documentHandle?.numPages || 1, source },
  }));
}

function dispatchDocumentLoaded() {
  window.dispatchEvent(new CustomEvent("pdf-document-loaded", {
    detail: { pages: documentHandle?.numPages || 1, url: sourceUrl },
  }));
}

function fitScaleFor(pageViewport) {
  const horizontalPadding = 30;
  const availableWidth = Math.max(240, viewportElement.clientWidth - horizontalPadding);
  return Math.max(.2, Math.min(2.5, availableWidth / pageViewport.width));
}

async function renderCurrentPage() {
  if (!documentHandle) return;
  const version = ++renderVersion;
  renderTask?.cancel();
  textLayer?.cancel?.();
  setLoading(`正在渲染第 ${currentPage} 页…`);

  try {
    const pdfPage = await documentHandle.getPage(currentPage);
    if (version !== renderVersion) return;
    const baseViewport = pdfPage.getViewport({ scale: 1 });
    if (zoomMode === "fit") currentScale = fitScaleFor(baseViewport);
    const pageViewport = pdfPage.getViewport({ scale: currentScale });
    const outputScale = Math.min(window.devicePixelRatio || 1, 2);
    const context = canvas.getContext("2d", { alpha: false });

    canvas.width = Math.floor(pageViewport.width * outputScale);
    canvas.height = Math.floor(pageViewport.height * outputScale);
    canvas.style.width = `${Math.floor(pageViewport.width)}px`;
    canvas.style.height = `${Math.floor(pageViewport.height)}px`;
    pageShell.style.width = canvas.style.width;
    pageShell.style.height = canvas.style.height;
    textLayerElement.replaceChildren();

    const transform = outputScale === 1 ? null : [outputScale, 0, 0, outputScale, 0, 0];
    renderTask = pdfPage.render({
      canvas,
      canvasContext: context,
      viewport: pageViewport,
      transform,
    });
    await renderTask.promise;
    if (version !== renderVersion) return;

    hideLoading();
    updateZoomLabel();
    activeThumbnail();

    const textContent = await pdfPage.getTextContent();
    if (version !== renderVersion) return;
    textLayer = new TextLayer({
      textContentSource: textContent,
      container: textLayerElement,
      viewport: pageViewport,
    });
    textLayer.render().catch((error) => {
      if (error?.name !== "AbortException") console.warn("PDF text layer failed", error);
    });
  } catch (error) {
    if (error instanceof RenderingCancelledException || error?.name === "RenderingCancelledException") return;
    console.error(error);
    setLoading(`页面无法渲染：${error.message || error}`, true);
  }
}

function scheduleFitRender() {
  clearTimeout(resizeTimer);
  resizeTimer = setTimeout(() => {
    if (zoomMode === "fit") renderCurrentPage();
  }, 120);
}

async function renderThumbnail(button) {
  if (!documentHandle || button.dataset.rendered === "true") return;
  button.dataset.rendered = "loading";
  try {
    const pageNumber = Number(button.dataset.page);
    const pdfPage = await documentHandle.getPage(pageNumber);
    const base = pdfPage.getViewport({ scale: 1 });
    const scale = Math.max(.08, Math.min(.32, 92 / base.width));
    const thumbViewport = pdfPage.getViewport({ scale });
    const thumbCanvas = button.querySelector("canvas");
    const context = thumbCanvas.getContext("2d", { alpha: false });
    thumbCanvas.width = Math.ceil(thumbViewport.width);
    thumbCanvas.height = Math.ceil(thumbViewport.height);
    await pdfPage.render({ canvas: thumbCanvas, canvasContext: context, viewport: thumbViewport }).promise;
    button.dataset.rendered = "true";
  } catch (error) {
    button.dataset.rendered = "error";
    button.title = `缩略图载入失败：${error.message || error}`;
  }
}

function buildThumbnails() {
  thumbnailObserver?.disconnect();
  thumbnailList.replaceChildren();
  thumbnailObserver = new IntersectionObserver((entries) => {
    entries.forEach((entry) => {
      if (!entry.isIntersecting) return;
      const button = entry.target;
      thumbnailObserver.unobserve(button);
      thumbnailQueue = thumbnailQueue.then(() => renderThumbnail(button));
    });
  }, { root: document.querySelector("#pdfThumbnails"), rootMargin: "180px 0px" });

  const fragment = document.createDocumentFragment();
  for (let pageNumber = 1; pageNumber <= documentHandle.numPages; pageNumber += 1) {
    const button = document.createElement("button");
    button.className = "thumbnail-item";
    button.type = "button";
    button.dataset.page = String(pageNumber);
    button.setAttribute("aria-label", `打开第 ${pageNumber} 页`);
    button.innerHTML = `<canvas aria-hidden="true"></canvas><span>${pageNumber}</span>`;
    button.addEventListener("click", () => setPage(pageNumber, { source: "thumbnail" }));
    fragment.append(button);
    thumbnailObserver.observe(button);
  }
  thumbnailList.append(fragment);
  activeThumbnail();
}

async function destroyDocument() {
  renderVersion += 1;
  renderTask?.cancel();
  textLayer?.cancel?.();
  thumbnailObserver?.disconnect();
  thumbnailList.replaceChildren();
  if (loadingTask) {
    try { await loadingTask.destroy(); } catch { /* already closed */ }
  } else if (documentHandle) {
    try { await documentHandle.destroy(); } catch { /* already closed */ }
  }
  loadingTask = null;
  documentHandle = null;
}

async function load(url, pageNumber = 1) {
  if (!url) return;
  if (sourceUrl === url && documentHandle) {
    setPage(pageNumber, { source: "app" });
    return;
  }

  await destroyDocument();
  sourceUrl = url;
  currentPage = Math.max(1, Number(pageNumber) || 1);
  zoomMode = "fit";
  setLoading("正在载入论文…");

  try {
    loadingTask = getDocument({
      url,
      cMapUrl: "/vendor/pdfjs/cmaps/",
      cMapPacked: true,
      standardFontDataUrl: "/vendor/pdfjs/standard_fonts/",
      wasmUrl: "/vendor/pdfjs/wasm/",
    });
    loadingTask.onProgress = ({ loaded, total }) => {
      if (documentHandle || !total) return;
      setLoading(`正在载入论文… ${Math.round((loaded / total) * 100)}%`);
    };
    documentHandle = await loadingTask.promise;
    currentPage = Math.min(documentHandle.numPages, currentPage);
    buildThumbnails();
    dispatchDocumentLoaded();
    dispatchPageChange("document");
    await renderCurrentPage();
  } catch (error) {
    console.error(error);
    setLoading(`论文载入失败：${error.message || error}`, true);
  }
}

function setPage(pageNumber, { source = "app" } = {}) {
  if (!documentHandle) return;
  const nextPage = Math.min(documentHandle.numPages, Math.max(1, Number(pageNumber) || 1));
  if (nextPage === currentPage && !pageShell.hidden) return;
  currentPage = nextPage;
  viewportElement.scrollTo({ top: 0, left: 0, behavior: "instant" });
  activeThumbnail();
  dispatchPageChange(source);
  renderCurrentPage();
}

function zoomBy(delta) {
  if (!documentHandle) return;
  zoomMode = "manual";
  currentScale = Math.max(.25, Math.min(3.5, currentScale + delta));
  renderCurrentPage();
}

document.querySelector("#zoomOut").addEventListener("click", () => zoomBy(-.15));
document.querySelector("#zoomIn").addEventListener("click", () => zoomBy(.15));
document.querySelector("#fitWidth").addEventListener("click", () => {
  zoomMode = "fit";
  renderCurrentPage();
});
thumbnailFold.addEventListener("click", () => {
  setThumbnailOpen(viewer.classList.contains("thumbnails-collapsed"));
});
viewportElement.addEventListener("keydown", (event) => {
  if (event.key === "ArrowLeft" || event.key === "PageUp") setPage(currentPage - 1, { source: "keyboard" });
  if (event.key === "ArrowRight" || event.key === "PageDown") setPage(currentPage + 1, { source: "keyboard" });
});
new ResizeObserver((entries) => {
  const width = Math.round(entries[0]?.contentRect?.width || 0);
  if (!observedViewportWidth) {
    observedViewportWidth = width;
    return;
  }
  if (Math.abs(width - observedViewportWidth) < 24) return;
  observedViewportWidth = width;
  scheduleFitRender();
}).observe(viewportElement);

setThumbnailOpen(localStorage.getItem("pdf-reader-thumbnails-open") !== "false");
window.pdfWorkbenchViewer = { load, setPage, fitWidth: () => { zoomMode = "fit"; renderCurrentPage(); } };
window.dispatchEvent(new Event("pdf-viewer-ready"));
