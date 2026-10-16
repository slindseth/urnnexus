import { MemoryProjectPanel } from "../components/MemoryProjectPanel";
import { useProjectPageContext } from "./ProjectPage";

export function ProjectReviewPage() {
  const { project } = useProjectPageContext();
  return (
    <MemoryProjectPanel
      key={project.projectName}
      projectName={project.projectName}
    />
  );
}
