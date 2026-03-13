from hypercore_sdk import HyperCoreAPI, SDKConfig, UnifiedStreamClient


def main() -> None:
    api_config = SDKConfig(api_key="replace-with-rpc-key")
    with HyperCoreAPI(api_config) as api:
        print({"btc_mid": api.coin_mid("BTC")})

    stream_config = SDKConfig(
        unified_stream_url="https://unified.grpc.aleatoric.systems",
        api_key="replace-with-unified-stream-key",
    )
    with UnifiedStreamClient(stream_config) as stream:
        print(stream.stats())


if __name__ == "__main__":
    main()
