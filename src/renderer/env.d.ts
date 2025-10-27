/// <reference types="vite/client" />

declare global {
	interface Window {
		electronAPI: {
			ping: () => Promise<string>;
			startAnonymize: (options: {
				inputPath: string;
				outputPath?: string;
				dataPackPath?: string;
				device?: string;
				classes?: string[];
				manualRois?: Array<[number, number, number, number]>;
				pythonPath?: string;
				modelPath?: string;
				aesKey?: string;
				hmacKey?: string;
				style?: string;
				disableDetection?: boolean;
				embedPack?: boolean;
				embeddedOutputPath?: string;
			}) => Promise<{
				jobId: string;
				outputPath: string;
				dataPackPath: string;
				embeddedOutputPath?: string;
			}>;
			cancelAnonymize: (jobId: string) => Promise<boolean>;
			onAnonymizeEvent: (
				callback: (payload: { jobId: string; event: string; [key: string]: unknown }) => void
			) => () => void;
			startRestore: (options: {
				anonymizedPath: string;
				dataPackPath?: string;
				outputPath?: string;
				aesKey: string;
				hmacKey?: string;
				pythonPath?: string;
				useEmbeddedPack?: boolean;
			}) => Promise<{ jobId: string; outputPath: string }>;
			cancelRestore: (jobId: string) => Promise<boolean>;
			onRestoreEvent: (
				callback: (payload: { jobId: string; event: string; [key: string]: unknown }) => void
			) => () => void;
		};
	}
}

export {}; // Ensure this file is treated as a module
