const video=document.querySelector('#walkthrough-video');
document.querySelectorAll('[data-chapter]').forEach(button=>button.addEventListener('click',()=>{
    if(!video)return;
    const time=Number(button.dataset.chapter);
    if(!Number.isFinite(time)||time<0)return;
    const seek=()=>{video.currentTime=time;video.play().catch(()=>{document.querySelector('#video-status').textContent='Press Play in the video controls to continue.'})};
    if(video.readyState>=1)seek();else video.addEventListener('loadedmetadata',seek,{once:true});
}));
if(video)video.addEventListener('error',()=>{document.querySelector('#video-status').textContent='The video could not load. Download the MP4 or open the transcript below.'});
