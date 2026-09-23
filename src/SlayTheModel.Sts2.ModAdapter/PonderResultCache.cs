namespace SlayTheModel.Sts2.ModAdapter;

internal sealed class PonderSearchFailedException(string stateKey, Exception innerException)
    : Exception($"Pondering failed before producing a result for state {stateKey}.", innerException);

internal sealed class PonderResultCache<T> where T : class
{
    private readonly object _gate = new();
    private string? _stateKey;
    private T? _latest;
    private TaskCompletionSource<T>? _first;

    public void Begin(string stateKey)
    {
        lock (_gate)
        {
            _stateKey = stateKey;
            _latest = null;
            _first = new TaskCompletionSource<T>(TaskCreationOptions.RunContinuationsAsynchronously);
        }
    }

    public bool Publish(string stateKey, T value)
    {
        TaskCompletionSource<T>? first;
        lock (_gate)
        {
            if (_stateKey != stateKey) return false;
            _latest = value;
            first = _first;
        }
        first?.TrySetResult(value);
        return true;
    }

    public bool TryGet(string stateKey, out T? value)
    {
        lock (_gate)
        {
            value = _stateKey == stateKey ? _latest : null;
            return value != null;
        }
    }

    /// <summary>
    /// Reports a failed speculative search. If an earlier slice already published a
    /// valid result, that result remains available. Otherwise the waiting decision is
    /// woken with a typed exception so it can fall back to a normal root search.
    /// </summary>
    public bool Fail(string stateKey, Exception exception)
    {
        TaskCompletionSource<T>? first;
        lock (_gate)
        {
            if (_stateKey != stateKey) return false;
            if (_latest != null) return true;
            first = _first;
        }
        first?.TrySetException(new PonderSearchFailedException(stateKey, exception));
        return true;
    }

    public Task<T> WaitForFirstAsync(string stateKey, CancellationToken cancellation)
    {
        lock (_gate)
        {
            if (_stateKey != stateKey || _first == null)
                throw new InvalidOperationException("No pondering search exists for the requested state.");
            return _latest != null ? Task.FromResult(_latest) : _first.Task.WaitAsync(cancellation);
        }
    }

    public void Clear()
    {
        lock (_gate)
        {
            _stateKey = null;
            _latest = null;
            _first = null;
        }
    }
}
