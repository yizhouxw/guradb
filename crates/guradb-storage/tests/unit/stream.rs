use super::*;
use futures::{stream, StreamExt};
use object_store::{
    GetResult, GetResultPayload, ListResult, MultipartUpload, ObjectMeta, PutMultipartOptions,
    PutOptions, PutPayload, PutResult,
};

#[derive(Debug)]
struct FaultStore {
    mode: &'static str,
    inner: object_store::memory::InMemory,
}
impl std::fmt::Display for FaultStore {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "FaultStore")
    }
}
#[async_trait::async_trait]
impl ObjectStore for FaultStore {
    async fn get_opts(
        &self,
        path: &ObjectPath,
        opts: GetOptions,
    ) -> object_store::Result<GetResult> {
        let mut result = self.inner.get_opts(path, opts).await?;
        result.payload = GetResultPayload::Stream(match self.mode {
            "overflow" => stream::iter([Ok(Bytes::from_static(b"xx"))]).boxed(),
            "failure" => stream::iter([Err(object_store::Error::NotImplemented)]).boxed(),
            _ => stream::pending().boxed(),
        });
        Ok(result)
    }
    async fn put_opts(
        &self,
        _: &ObjectPath,
        _: PutPayload,
        _: PutOptions,
    ) -> object_store::Result<PutResult> {
        Err(object_store::Error::NotImplemented)
    }
    async fn put_multipart_opts(
        &self,
        _: &ObjectPath,
        _: PutMultipartOptions,
    ) -> object_store::Result<Box<dyn MultipartUpload>> {
        Err(object_store::Error::NotImplemented)
    }
    async fn delete(&self, _: &ObjectPath) -> object_store::Result<()> {
        Err(object_store::Error::NotImplemented)
    }
    fn list(
        &self,
        _: Option<&ObjectPath>,
    ) -> futures::stream::BoxStream<'static, object_store::Result<ObjectMeta>> {
        stream::empty().boxed()
    }
    async fn list_with_delimiter(
        &self,
        _: Option<&ObjectPath>,
    ) -> object_store::Result<ListResult> {
        Err(object_store::Error::NotImplemented)
    }
    async fn copy(&self, _: &ObjectPath, _: &ObjectPath) -> object_store::Result<()> {
        Err(object_store::Error::NotImplemented)
    }
    async fn copy_if_not_exists(&self, _: &ObjectPath, _: &ObjectPath) -> object_store::Result<()> {
        Err(object_store::Error::NotImplemented)
    }
}

#[tokio::test]
async fn untrusted_object_stream_overflow_failure_and_cancel() {
    for (mode, code) in [
        ("overflow", "source_invalid"),
        ("failure", "source_unavailable"),
        ("pending", "cancelled"),
    ] {
        let store = FaultStore {
            mode,
            inner: object_store::memory::InMemory::new(),
        };
        store
            .inner
            .put(&ObjectPath::from("data"), PutPayload::from_static(b"x"))
            .await
            .unwrap();
        let source = Source::S3(Arc::new(store));
        let file = Fragment {
            fragment_id: "f".into(),
            key: "data".into(),
            size_bytes: 1,
            sha256: digest(b"x"),
            version_id: None,
        };
        let cancel = CancellationToken::new();
        let wait = async {
            if mode == "pending" {
                tokio::task::yield_now().await;
                cancel.cancel();
            }
        };
        let (result, _) = tokio::join!(source.read(&file, &cancel), wait);
        assert_eq!(result.unwrap_err().code, code);
    }
}
