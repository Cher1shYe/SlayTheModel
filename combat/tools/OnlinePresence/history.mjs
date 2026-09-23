const MINUTE = 60000;
const INTERVALS = [1,2,5,10,15,30,60,120,180,360,720,1440];

export function aggregateHistory(rows, hours, maxPoints) {
  const minutes = INTERVALS.find(value => value >= hours * 60 / maxPoints);
  if (minutes === undefined) throw new RangeError('Unsupported history range');
  const intervalMs = minutes * MINUTE;
  const history = [];
  let bucket;
  let previous;
  let historyPeak = 0;
  for (const row of rows) {
    historyPeak = Math.max(historyPeak,row.count);
    const key = Math.floor(row.time / intervalMs);
    const breakBefore = previous !== undefined && row.time - previous > 90000;
    if (!bucket || bucket.key !== key || breakBefore) {
      bucket = {key, sum:0, point:{time:row.time,count:0,start:row.time,end:row.time,samples:0,breakBefore}};
      history.push(bucket.point);
    }
    bucket.sum += row.count;
    bucket.point.samples++;
    bucket.point.end = row.time;
    bucket.point.time = Math.floor((bucket.point.start + row.time) / 2);
    bucket.point.count = bucket.sum / bucket.point.samples;
    previous = row.time;
  }
  return {history,historyPeak,intervalMs};
}
