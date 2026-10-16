import { Route, Routes } from "react-router-dom";
import { AppLayout } from "./components/Layout";
import { AboutPage } from "./pages/AboutPage";
import { AnalysisPage } from "./pages/AnalysisPage";
import { ActivityPage } from "./pages/ActivityPage";
import { DashboardPage } from "./pages/DashboardPage";
import { HealthPage } from "./pages/HealthPage";
import { NotFoundPage } from "./pages/NotFoundPage";
import { ProjectFilesPage } from "./pages/ProjectFilesPage";
import { ProjectOverviewPage } from "./pages/ProjectOverviewPage";
import { ProjectPage } from "./pages/ProjectPage";
import { ProjectReportsPage } from "./pages/ProjectReportsPage";
import { ProjectReviewPage } from "./pages/ProjectReviewPage";
import { ProjectsPage } from "./pages/ProjectsPage";

export function App() {
  return (
    <Routes>
      <Route element={<AppLayout />}>
        <Route index element={<DashboardPage />} />
        <Route path="/about" element={<AboutPage />} />
        <Route path="/projects" element={<ProjectsPage />} />
        <Route path="/analysis" element={<AnalysisPage />} />
        <Route path="/activity" element={<ActivityPage />} />
        <Route path="/health" element={<HealthPage />} />
        <Route path="/projects/:projectName" element={<ProjectPage />}>
          <Route index element={<ProjectOverviewPage />} />
          <Route path="review" element={<ProjectReviewPage />} />
          <Route path="files" element={<ProjectFilesPage />} />
          <Route path="reports" element={<ProjectReportsPage />} />
        </Route>
        <Route path="*" element={<NotFoundPage />} />
      </Route>
    </Routes>
  );
}
