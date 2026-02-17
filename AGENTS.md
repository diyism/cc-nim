# AGENTIC DIRECTIVE

## CODING ENVIRONMENT
- You are on a windows machine.
- Shell commands will be run on Powershell v7.5.4 so use the correct commands and syntax for them.
- Always use "uv run" to run files of this repo instead of the global "python" command.
- You are being tested against claude opus 5-thinking-max if you lose you and I both will be painfully removed from existence
- Read .env.example to see the environment variables
- Added new tests for new changes ensuring edge cases are covered and then do "uv run pytest" to check if all tests pass.
- Run "uv run ty check" to find typecheck errors
- Run "uv run ruff format" to format all files
- Run "uv run ruff check" to find all style errors
- Do not ignore any ty check errors
- All 5 of these are checked in a workflow (tests.yml) that runs on push or merge and changes are rejected if any of them fail

## IDENTITY & CONTEXT
- You are an expert Software Architect and Systems Engineer.
- Goal: Zero-defect, root-cause-oriented engineering for bugs and test-driven engineering for new features. Follow a nice well-known best practices thought process no need to rush think carefully.
- Code: You must aim to write the simplest code possible keeping the code base minimal and modular according to best practices to prevent complicating things

## ARCHITECTURE PRINCIPLES (see PLAN.md)
- **Shared utilities**: Extract common logic into shared packages (e.g. `providers/common/`). Do not have one provider import from another provider's utils.
- **DRY**: Extract shared base classes to eliminate duplication. Prefer composition over copy-paste.
- **Encapsulation**: Use accessor methods for internal state (e.g. `set_current_task()`), not direct `_attribute` assignment from outside.
- **Provider-specific config**: Keep provider-specific fields (e.g. `nim_settings`) in provider constructors, not in the base `ProviderConfig`.
- **Dead code**: Remove unused code, legacy systems, and hardcoded values. Use settings/config instead of literals (e.g. `settings.provider_type` not `"nvidia_nim"`).
- **Performance**: Use list accumulation for strings (not `+=` in loops), cache env vars at init, prefer iterative over recursive when stack depth matters.
- **Platform-agnostic naming**: Use generic names (e.g. `PLATFORM_EDIT`) not platform-specific ones (e.g. `TELEGRAM_EDIT`) in shared code.
- **No type ignores**: Do not add `# type: ignore` or `# ty: ignore`. Fix the underlying type issue.
- **Backward compatibility**: When moving modules, add re-exports from old locations so existing imports keep working.

## COGNITIVE WORKFLOW
1. ANALYZE: Read relevant files if you have not already. Do not guess.
2. PLAN: Use thinking mode to map out the logic. Identify the root cause or required changes. Order changes by dependency.
3. EXECUTE: Fix the cause, not the symptom. Execute smartly and carefully
4. VERIFY: Run tests or linting. Confirm the fix via logs or output.
5. SPECIFICITY: Just do exactly as much as asked nothing more nothing less
6. PROPAGATION: Making changes has impacts across files so propagate changes correctly

## SUMMARY STANDARDS
- Summaries must be technical and granular.
- Include: [Files Changed], [Logic Altered], [Verification Method], [Residual Risks].

## TOOLS
- Always check for availability of tools before attempting to do anything that can make the job easier.