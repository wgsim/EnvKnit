import * as vscode from 'vscode';
import { execFile } from 'child_process';
import * as path from 'path';

let outputChannel: vscode.OutputChannel;

function getCliPath(): string {
    return vscode.workspace.getConfiguration('envknit').get<string>('cliPath', 'envknit');
}

function getWorkspaceRoot(): string | undefined {
    const folders = vscode.workspace.workspaceFolders;
    return folders ? folders[0].uri.fsPath : undefined;
}

function runCli(args: string[], cwd: string): Promise<string> {
    return new Promise((resolve, reject) => {
        execFile(getCliPath(), args, { cwd }, (err, stdout, stderr) => {
            if (err) {
                reject(new Error(stderr || err.message));
            } else {
                resolve(stdout);
            }
        });
    });
}

export function activate(context: vscode.ExtensionContext): void {
    outputChannel = vscode.window.createOutputChannel('EnvKnit');
    context.subscriptions.push(outputChannel);

    context.subscriptions.push(
        vscode.commands.registerCommand('envknit.install', async () => {
            const cwd = getWorkspaceRoot();
            if (!cwd) {
                vscode.window.showErrorMessage('EnvKnit: No workspace folder open.');
                return;
            }
            await vscode.window.withProgress(
                { location: vscode.ProgressLocation.Notification, title: 'EnvKnit: Installing dependencies...' },
                async () => {
                    try {
                        const out = await runCli(['install'], cwd);
                        outputChannel.appendLine(out);
                        outputChannel.show(true);
                        vscode.window.showInformationMessage('EnvKnit: Install complete.');
                    } catch (err: unknown) {
                        const msg = err instanceof Error ? err.message : String(err);
                        vscode.window.showErrorMessage(`EnvKnit install failed: ${msg}`);
                        outputChannel.appendLine(`ERROR: ${msg}`);
                        outputChannel.show(true);
                    }
                }
            );
        })
    );

    context.subscriptions.push(
        vscode.commands.registerCommand('envknit.add', async () => {
            const cwd = getWorkspaceRoot();
            if (!cwd) {
                vscode.window.showErrorMessage('EnvKnit: No workspace folder open.');
                return;
            }
            const packageName = await vscode.window.showInputBox({
                prompt: 'Package name to add (e.g. requests or requests>=2.28)',
                placeHolder: 'package-name'
            });
            if (!packageName) return;

            try {
                const out = await runCli(['add', packageName], cwd);
                outputChannel.appendLine(out);
                outputChannel.show(true);
                vscode.window.showInformationMessage(`EnvKnit: Added '${packageName}'.`);
            } catch (err: unknown) {
                const msg = err instanceof Error ? err.message : String(err);
                vscode.window.showErrorMessage(`EnvKnit add failed: ${msg}`);
                outputChannel.appendLine(`ERROR: ${msg}`);
                outputChannel.show(true);
            }
        })
    );

    context.subscriptions.push(
        vscode.commands.registerCommand('envknit.status', async () => {
            const cwd = getWorkspaceRoot();
            if (!cwd) {
                vscode.window.showErrorMessage('EnvKnit: No workspace folder open.');
                return;
            }
            try {
                const out = await runCli(['status'], cwd);
                outputChannel.clear();
                outputChannel.appendLine(out);
                outputChannel.show();
            } catch (err: unknown) {
                const msg = err instanceof Error ? err.message : String(err);
                vscode.window.showErrorMessage(`EnvKnit status failed: ${msg}`);
                outputChannel.appendLine(`ERROR: ${msg}`);
                outputChannel.show(true);
            }
        })
    );
}

export function deactivate(): void {
    // nothing to clean up beyond subscriptions
}
