import React from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Route, Routes } from "react-router-dom";
import "./index.css";
import Layout from "@/components/Layout";
import Home from "@/pages/Home";
import ScanPage from "@/pages/ScanPage";
import HistoryPage from "@/pages/HistoryPage";
import LeaderboardPage from "@/pages/LeaderboardPage";
import FixesPage from "@/pages/FixesPage";

createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <BrowserRouter>
      <Routes>
        <Route element={<Layout />}>
          <Route index element={<Home />} />
          <Route path="history" element={<HistoryPage />} />
          <Route path="leaderboard" element={<LeaderboardPage />} />
          <Route path="scan/:id" element={<ScanPage />} />
          <Route path="scan/:id/fixes" element={<FixesPage />} />
          <Route path="*" element={<Home />} />
        </Route>
      </Routes>
    </BrowserRouter>
  </React.StrictMode>,
);
