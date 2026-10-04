import { QueryClientProvider } from "@tanstack/react-query";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import App from "./App";
import { createQueryClient } from "./api/hooks";
import { copy } from "./copy/en";
import "./index.css";

const root = document.getElementById("root");
if (root === null) {
  throw new Error("The #root element is missing from index.html");
}

document.title = copy.app.title;

createRoot(root).render(
  <StrictMode>
    <QueryClientProvider client={createQueryClient()}>
      <App />
    </QueryClientProvider>
  </StrictMode>,
);
