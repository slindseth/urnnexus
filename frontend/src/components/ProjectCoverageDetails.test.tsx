import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { ProjectCoverageDetails } from "./ProjectCoverageDetails";

describe("project coverage", () => {
  it("keeps SMC exclusions visible independently of successful synchronization", () => {
    const html = renderToStaticMarkup(
      <ProjectCoverageDetails
        coverage={{
          sync_status: "complete",
          enumeration_complete: true,
          analysis_status: "partial",
          historical_analysis_exclusions: [
            {
              relative_path: "Tegninger/modell.smc",
              reason: "unsupported_format",
              download_selected: false,
            },
          ],
          historical_coverage_diagnostics: [
            { message: "Unreadable source.pdf", observed_at: null },
          ],
        }}
      />,
    );
    expect(html).toContain("Fullført");
    expect(html).toContain("partial");
    expect(html).toContain("modell.smc");
    expect(html).toContain("unsupported_format");
    expect(html).toContain("Unreadable source.pdf");
    expect(html).not.toContain("<button");
  });
});
