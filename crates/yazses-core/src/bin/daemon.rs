use tracing_subscriber::{fmt, prelude::*, EnvFilter};
use yazses_core::daemon::Daemon;

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    tracing_subscriber::registry()
        .with(fmt::layer())
        .with(EnvFilter::from_default_env().add_directive("yazses=info".parse()?))
        .init();

    Daemon::new().run().await
}
