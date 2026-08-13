import { api } from "@/utils/api";

export interface DocumentItem {
  id: string;
  dbId: number;
  parsedDocId?: number;
  name: string;
  kb: string;
  status: "Queued" | "Uploaded" | "Parsing" | "Parsed" | "Failed";
  chunks: number;
  lang: "AR" | "EN" | "Bilingual";
  date: string;
  size: string;
  pages?: number;
  characters?: number;
  processingTime?: number;
  parserName?: string;
  errorDetail?: string;
  classification?: string;
}

const formatBytes = (bytes: number, decimals = 2) => {
  if (bytes === 0) return "0 Bytes";
  const k = 1024;
  const dm = decimals < 0 ? 0 : decimals;
  const sizes = ["Bytes", "KB", "MB", "GB"];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return parseFloat((bytes / Math.pow(k, i)).toFixed(dm)) + " " + sizes[i];
};

export const DocumentsService = {
  async getDocuments(): Promise<DocumentItem[]> {
    try {
      const res = await api.get("/documents");
      return res.data.map((doc: any) => {
        let status: "Queued" | "Uploaded" | "Parsing" | "Parsed" | "Failed" = "Queued";
        if (doc.status === "Parsed" || doc.status === "Ready") {
          status = "Parsed";
        } else if (doc.status === "Parsing" || doc.status === "Chunking") {
          status = "Parsing";
        } else if (doc.status === "Uploaded" || doc.status === "Ready for Parsing" || doc.status === "Pending Scan") {
          status = "Uploaded";
        } else if (doc.status === "Failed") {
          status = "Failed";
        } else {
          status = "Queued";
        }

        let lang: "AR" | "EN" | "Bilingual" = "EN";
        if (doc.language === "ar") {
          lang = "AR";
        } else if (doc.language === "mixed" || doc.language === "bilingual") {
          lang = "Bilingual";
        }

        return {
          id: doc.uuid,
          dbId: doc.id,
          parsedDocId: doc.parsed_document_id ?? undefined,
          name: doc.filename,
          kb: doc.knowledge_base_uuid,
          status,
          chunks: doc.chunk_count || 0,
          lang,
          date: new Date(doc.created_at).toLocaleDateString(),
          size: formatBytes(doc.file_size),
          pages: doc.pages ?? undefined,
          characters: doc.characters ?? undefined,
          processingTime: doc.processing_time ?? undefined,
          parserName: doc.parser_name ?? undefined,
          errorDetail: doc.error_message ?? undefined,
          classification: doc.classification || "Technical Documentation"
        };
      });
    } catch (e) {
      console.error("Error fetching documents", e);
      return [];
    }
  },

  async uploadDocument(
    file: File,
    kbUuid: string,
    onProgress?: (percent: number) => void
  ): Promise<DocumentItem> {
    const formData = new FormData();
    formData.append("file", file);
    formData.append("knowledge_base_uuid", kbUuid);

    const res = await api.post("/documents/upload", formData, {
      headers: {
        "Content-Type": "multipart/form-data"
      },
      onUploadProgress: (progressEvent) => {
        if (onProgress && progressEvent.total) {
          const percent = Math.round((progressEvent.loaded * 100) / progressEvent.total);
          onProgress(percent);
        }
      }
    });

    const doc = res.data;
    return {
      id: doc.uuid,
      dbId: doc.id,
      parsedDocId: doc.parsed_document_id ?? undefined,
      name: doc.filename,
      kb: doc.knowledge_base_uuid,
      status: "Uploaded",
      chunks: 0,
      lang: "EN",
      date: new Date(doc.created_at).toLocaleDateString(),
      size: formatBytes(doc.file_size),
      classification: doc.classification || "Technical Documentation"
    };
  },

  async deleteDocument(id: string): Promise<boolean> {
    await api.delete(`/documents/${id}`);
    return true;
  },

  async getDocumentInsights(id: string): Promise<any> {
    try {
      const res = await api.get(`/documents/${id}/insights`);
      return res.data;
    } catch (e) {
      console.error(`Error fetching insights for doc ${id}`, e);
      return null;
    }
  },
};

